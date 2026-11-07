"""Native Brightcove Video Cloud CMS metadata and catalog management.

Client grants are account-bound forms, not a global OAuth callback. Media URLs
and assets are never returned; permissions here are a local ceiling, not proof.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

CMS_ROOT = "https://cms.api.brightcove.com/v1/accounts/"
TOKEN_URL = "https://oauth.brightcove.com/v4/access_token"
HIDDEN = {"ui:hidden": True}
SECRET = {"ui:widget": "password"}
Permission = Literal["video-cloud/video/read", "video-cloud/video/create",
    "video-cloud/video/update", "video-cloud/video/delete", "video-cloud/video/all",
    "video-cloud/playlist/read", "video-cloud/playlist/create", "video-cloud/playlist/update",
    "video-cloud/playlist/delete", "video-cloud/playlist/all"]


def _id(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,23}", value):
        raise ValueError("Enter one numeric Brightcove account, video or playlist ID.")
    return value


def _folder_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Enter one Brightcove folder ID.")
    return value


def _label_path(value):
    if not isinstance(value, str) or len(value) > 1024 or not value.startswith("/"):
        raise ValueError("Enter a non-root label path starting with /.")
    parts = value.rstrip("/").split("/")[1:]
    if not parts or len(parts) > 20 or any(not part or part in {".", ".."} or
        len(part) > 100 or re.search(r"[\\%?#\x00-\x1f]", part) for part in parts):
        raise ValueError("Use a non-root label path without URL or traversal characters.")
    return "/" + "/".join(parts)


class BrightcoveClientCredential(BaseModel):
    """Customer-created Video Cloud client credentials for one selected account."""
    credential_type: Literal["brightcove_client_credentials"] = Field("brightcove_client_credentials", json_schema_extra=HIDDEN)
    account_id: str = Field(..., title="Video Cloud Account ID")
    client_id: str = Field(..., min_length=1, max_length=1024, title="Client ID")
    client_secret: str = Field(..., min_length=1, max_length=4096, title="Client Secret", json_schema_extra=SECRET)
    permissions: list[Permission] = Field(default_factory=lambda: ["video-cloud/video/read", "video-cloud/playlist/read"],
        min_length=1, max_length=10, title="Local Operations Ceiling",
        description="Select a subset of permissions configured for this client in Brightcove Studio. This form does not grant access; Brightcove authorizes each request.")
    access_token: Optional[str] = Field(None, json_schema_extra=HIDDEN)
    expires_at: Optional[str] = Field(None, json_schema_extra=HIDDEN)
    token_type: Optional[Literal["Bearer"]] = Field(None, json_schema_extra=HIDDEN)
    model_config = ConfigDict(title="Brightcove API Client", extra="forbid", json_schema_extra={
        "x-credential-url": "https://studio.support.brightcove.com/admin/managing-api-authentication-credentials.html"})

    @field_validator("account_id", mode="before")
    @classmethod
    def account_value(cls, value):
        return _id(value)

    @field_validator("client_id", "client_secret", "access_token")
    @classmethod
    def secret_value(cls, value):
        if value is None:
            return None
        value = clean_secret(value)
        if not value or re.search(r"[\x00-\x20\x7f]", value):
            raise ValueError("Use a nonempty credential value without whitespace.")
        return value

    @field_validator("client_id")
    @classmethod
    def client_value(cls, value):
        if ":" in value:
            raise ValueError("Client ID cannot contain a Basic authentication separator.")
        return value

    @field_validator("permissions")
    @classmethod
    def permissions_value(cls, value):
        return sorted(set(value))

    @model_validator(mode="after")
    def finite_token(self):
        if any(value is not None for value in (self.access_token, self.expires_at, self.token_type)):
            try:
                expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            except (AttributeError, TypeError, ValueError):
                raise ValueError("Brightcove token requires its actual expiry.") from None
            if not self.access_token or self.token_type != "Bearer" or expiry.tzinfo is None:
                raise ValueError("Brightcove token and aware expiry must be supplied together.")
        return self


def _credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != "brightcove_client_credentials" or data.get("refresh_token"):
        raise ValueError("A saved Brightcove client-credentials connection is required.")
    try:
        fields = {key: value for key, value in data.items() if key in BrightcoveClientCredential.model_fields}
        shaped = BrightcoveClientCredential.model_validate(fields).model_dump(mode="json")
    except Exception:
        raise ValueError("Brightcove credential fields or account binding are invalid.") from None
    return {**data, **shaped}


def _ready(data):
    return bool(data.get("access_token") and data.get("expires_at") and
        datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc) + timedelta(seconds=30))


def _permission(data, resource, action="read"):
    required = "video-cloud/" + resource + "/" + action
    if required not in data["permissions"] and "video-cloud/" + resource + "/all" not in data["permissions"]:
        raise ValueError("Enable the needed Brightcove operation in this connection's local ceiling and client permissions.")


async def _mint(data):
    data = _credential(data)
    basic = base64.b64encode((data["client_id"] + ":" + data["client_secret"]).encode()).decode()
    try:
        async with guarded_async_client( timeout=20.0, trust_env=False, follow_redirects=False) as client:
            response = await client.post(TOKEN_URL, data={"grant_type": "client_credentials"},
                headers={"Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    except Exception:
        raise RuntimeError("Brightcove token request could not complete.") from None
    if response.status_code != 200 or len(response.content) > 100_000:
        raise RuntimeError("Brightcove token issuance is unverified; check client credentials and retry later.")
    try:
        payload = response.json()
        ttl = payload["expires_in"]
        if not isinstance(payload, dict) or type(ttl) is not int or not 0 < ttl <= 86400 or payload.get("token_type", "").lower() != "bearer" or payload.get("refresh_token"):
            raise ValueError()
        token = clean_secret(payload["access_token"])
        if not token or re.search(r"[\x00-\x20\x7f]", token):
            raise ValueError()
    except Exception:
        raise RuntimeError("Brightcove returned an incomplete finite token response.") from None
    return {**data, "access_token": token, "token_type": "Bearer",
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()}


def _selector(field, parent=None):
    options = {"field_name": field, "searchable": True, "allow_custom": True}
    if parent:
        options["depends_on"] = parent
    resource = "video" if field == "folder_video_id" else "label" if field == "label_path" else field.removesuffix("_id")
    return {"x-dynamic-options": options, "x-resource-type": "brightcove_" + resource}


class BrightcoveOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrightcovePage(BrightcoveOperation):
    limit: int = Field(25, ge=1, le=100)
    offset: int = Field(0, ge=0, le=1_000_000)
    page_token: Optional[str] = Field(None, max_length=4096)


class BrightcoveListVideosConfig(BrightcovePage):
    operation: Literal["list_videos"] = Field("list_videos", description="Read projected video metadata with bounded offset pagination.",
        json_schema_extra={"x-display-name": "List Videos", "x-category": "Videos"})
    q: Optional[str] = Field(None, max_length=1024, title="Video Search",
        description="Documented CMS v1 search expression, e.g. tags:training. Offset pages are not a snapshot.")
    sort: Literal["name", "-name", "updated_at", "-updated_at", "created_at", "-created_at"] = "-updated_at"


class BrightcoveVideo(BrightcoveOperation):
    video_id: str = Field(..., title="Video", json_schema_extra=_selector("video_id"))
    _validate_video = field_validator("video_id", mode="before")(_id)


class BrightcoveGetVideoConfig(BrightcoveVideo):
    operation: Literal["get_video"] = Field("get_video", description="Read one video in the selected Video Cloud account.",
        json_schema_extra={"x-display-name": "Get Video", "x-category": "Videos"})


class BrightcoveCountConfig(BrightcoveOperation):
    operation: Literal["get_catalog_counts"] = Field("get_catalog_counts", description="Read current video and playlist counts; these are not playback analytics.",
        json_schema_extra={"x-display-name": "Get Catalog Counts", "x-category": "Catalog"})


class BrightcoveVideoFields(BrightcoveOperation):
    name: Optional[str] = Field(None, min_length=1, max_length=250)
    description: Optional[str] = Field(None, max_length=250)
    long_description: Optional[str] = Field(None, max_length=5000)
    reference_id: Optional[str] = Field(None, max_length=150)
    tags: Optional[list[str]] = Field(None, max_length=100)
    custom_fields: Optional[dict[str, Optional[str]]] = Field(None, description="Internal custom field names; strings or null to clear.")
    labels: Optional[list[str]] = Field(None, max_length=100, description="Full existing label paths; account must have labels enabled.")

    @field_validator("tags")
    @classmethod
    def tags_value(cls, value):
        if value is not None and any(not tag or len(tag) > 128 or "," in tag for tag in value):
            raise ValueError("Tags must be nonempty, at most 128 characters, without commas.")
        return value

    @field_validator("custom_fields")
    @classmethod
    def custom_values(cls, value):
        if value is not None and (len(value) > 100 or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key) or
            item is not None and (len(item.encode()) > 1024) for key, item in value.items())):
            raise ValueError("Use bounded internal custom field names and values.")
        return value

    @field_validator("labels")
    @classmethod
    def labels_value(cls, value):
        return [_label_path(item) for item in value] if value is not None else None


class BrightcoveCreateVideoConfig(BrightcoveVideoFields):
    """Create an inactive metadata placeholder without ingesting media."""
    operation: Literal["create_video_draft"] = Field("create_video_draft", description="Create an inactive metadata placeholder without media ingest.",
        json_schema_extra={"x-display-name": "Create Video Draft", "x-category": "Videos"})
    name: str = Field(..., min_length=1, max_length=250)
    labels: None = Field(None, json_schema_extra=HIDDEN)


class BrightcoveUpdateVideoConfig(BrightcoveVideo, BrightcoveVideoFields):
    """Update catalog metadata. Existing Brightcove video-change subscriptions may fire."""
    operation: Literal["update_video_metadata"] = Field("update_video_metadata", description="Update metadata; existing video-change subscriptions may fire.",
        json_schema_extra={"x-display-name": "Update Video Metadata", "x-category": "Videos"})

    @model_validator(mode="after")
    def require_change(self):
        if all(getattr(self, key) is None for key in ("name", "description", "long_description", "reference_id", "tags", "custom_fields", "labels")):
            raise ValueError("Supply at least one metadata field.")
        return self


class BrightcoveDeleteVideoConfig(BrightcoveVideo):
    """Delete a video record and its associated assets."""
    operation: Literal["delete_video"] = Field("delete_video", description="Delete a video record and its associated assets.",
        json_schema_extra={"x-display-name": "Delete Video", "x-category": "Videos"})


class BrightcoveListPlaylistsConfig(BrightcovePage):
    operation: Literal["list_playlists"] = Field("list_playlists", description="Read account playlist metadata with bounded pagination.",
        json_schema_extra={"x-display-name": "List Playlists", "x-category": "Playlists"})
    q: Optional[str] = Field(None, max_length=1024)
    sort: Literal["name", "-name", "updated_at", "-updated_at"] = "-updated_at"


class BrightcovePlaylist(BrightcoveOperation):
    playlist_id: str = Field(..., title="Playlist", json_schema_extra=_selector("playlist_id"))
    _validate_playlist = field_validator("playlist_id", mode="before")(_id)


class BrightcoveGetPlaylistConfig(BrightcovePlaylist):
    operation: Literal["get_playlist"] = Field("get_playlist", description="Read a playlist in the selected account.",
        json_schema_extra={"x-display-name": "Get Playlist", "x-category": "Playlists"})


class BrightcoveListPlaylistVideosConfig(BrightcovePlaylist, BrightcovePage):
    operation: Literal["list_playlist_videos"] = Field("list_playlist_videos", description="Read video metadata under a current account playlist.",
        json_schema_extra={"x-display-name": "List Playlist Videos", "x-category": "Playlists"})


class BrightcovePlaylistFields(BrightcoveOperation):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=255)
    reference_id: Optional[str] = Field(None, max_length=150)
    favorite: Optional[bool] = None
    video_ids: Optional[list[str]] = Field(None, max_length=1000, description="Complete replacement membership for a manual playlist.")
    _validate_videos = field_validator("video_ids")(lambda value: [_id(item) for item in value] if value is not None else None)


class BrightcoveCreatePlaylistConfig(BrightcovePlaylistFields):
    operation: Literal["create_manual_playlist"] = Field("create_manual_playlist", description="Create an explicit playlist with optional video membership.",
        json_schema_extra={"x-display-name": "Create Manual Playlist", "x-category": "Playlists"})
    name: str = Field(..., min_length=1, max_length=255)
    video_ids: list[str] = Field(default_factory=list, max_length=1000)


class BrightcoveUpdatePlaylistConfig(BrightcovePlaylist, BrightcovePlaylistFields):
    operation: Literal["update_playlist"] = Field("update_playlist", description="Update metadata or replace a manual playlist's membership.",
        json_schema_extra={"x-display-name": "Update Playlist", "x-category": "Playlists"})

    @model_validator(mode="after")
    def require_change(self):
        if all(getattr(self, key) is None for key in ("name", "description", "reference_id", "favorite", "video_ids")):
            raise ValueError("Supply at least one playlist metadata field.")
        return self


class BrightcoveDeletePlaylistConfig(BrightcovePlaylist):
    operation: Literal["delete_playlist"] = Field("delete_playlist", description="Delete a playlist in the selected account.",
        json_schema_extra={"x-display-name": "Delete Playlist", "x-category": "Playlists"})


class BrightcoveListFoldersConfig(BrightcovePage):
    operation: Literal["list_folders"] = Field("list_folders", description="Read locally paged account folder metadata.",
        json_schema_extra={"x-display-name": "List Folders", "x-category": "Folders"})


class BrightcoveFolder(BrightcoveOperation):
    folder_id: str = Field(..., title="Folder", json_schema_extra=_selector("folder_id"))
    _validate_folder = field_validator("folder_id", mode="before")(_folder_id)


class BrightcoveGetFolderConfig(BrightcoveFolder):
    operation: Literal["get_folder"] = Field("get_folder", description="Read current folder metadata.",
        json_schema_extra={"x-display-name": "Get Folder", "x-category": "Folders"})


class BrightcoveListFolderVideosConfig(BrightcoveFolder, BrightcovePage):
    operation: Literal["list_folder_videos"] = Field("list_folder_videos", description="Read videos under the selected current folder.",
        json_schema_extra={"x-display-name": "List Folder Videos", "x-category": "Folders"})
    sort: Literal["name", "-name", "updated_at", "-updated_at"] = "-updated_at"


class BrightcoveFolderName(BrightcoveOperation):
    name: str = Field(..., min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def folder_name(cls, value):
        if not value.strip() or "/" in value:
            raise ValueError("Folder names cannot be blank or contain /.")
        return value


class BrightcoveCreateFolderConfig(BrightcoveFolderName):
    operation: Literal["create_folder"] = Field("create_folder", description="Create an account folder with a unique name.",
        json_schema_extra={"x-display-name": "Create Folder", "x-category": "Folders"})


class BrightcoveRenameFolderConfig(BrightcoveFolder, BrightcoveFolderName):
    operation: Literal["rename_folder"] = Field("rename_folder", description="Rename the selected account folder.",
        json_schema_extra={"x-display-name": "Rename Folder", "x-category": "Folders"})


class BrightcoveDeleteFolderConfig(BrightcoveFolder, BrightcoveFolderName):
    """Delete only an empty folder after matching its current name."""
    operation: Literal["delete_empty_folder"] = Field("delete_empty_folder", description="Delete only an empty folder after matching its current name.",
        json_schema_extra={"x-display-name": "Delete Empty Folder", "x-category": "Folders"})


class BrightcoveAddFolderVideoConfig(BrightcoveFolder, BrightcoveVideo):
    """Move a video into the selected folder; a video can belong to only one folder."""
    operation: Literal["add_video_to_folder"] = Field("add_video_to_folder", description="Move an account video into this folder.",
        json_schema_extra={"x-display-name": "Add Video to Folder", "x-category": "Folders"})


class BrightcoveRemoveFolderVideoConfig(BrightcoveFolder, BrightcoveVideo):
    operation: Literal["remove_video_from_folder"] = Field("remove_video_from_folder", description="Remove a video only when it currently belongs to this folder.",
        json_schema_extra={"x-display-name": "Remove Video from Folder", "x-category": "Folders"})
    video_id: str = Field(..., title="Video in Folder", json_schema_extra=_selector("folder_video_id", "folder_id"))


class BrightcoveFieldsConfig(BrightcoveOperation):
    operation: Literal["get_video_fields"] = Field("get_video_fields", description="Read projected standard and custom field definitions.",
        json_schema_extra={"x-display-name": "Get Video Fields", "x-category": "Catalog"})


class BrightcoveListLabelsConfig(BrightcovePage):
    operation: Literal["list_labels"] = Field("list_labels", description="Read account label paths when labels are enabled.",
        json_schema_extra={"x-display-name": "List Labels", "x-category": "Labels"})


class BrightcoveCreateLabelConfig(BrightcoveOperation):
    """Create a label path and missing ancestors; labels must be enabled on the account."""
    operation: Literal["create_label"] = Field("create_label", description="Create a label path and missing ancestors.",
        json_schema_extra={"x-display-name": "Create Label", "x-category": "Labels"})
    path: str = Field(..., max_length=1024)
    _validate_path = field_validator("path")(_label_path)


class BrightcoveExistingLabel(BrightcoveOperation):
    label_path: str = Field(..., title="Label", json_schema_extra=_selector("label_path"))
    _validate_label = field_validator("label_path")(_label_path)


class BrightcoveRenameLabelConfig(BrightcoveExistingLabel):
    """Rename the last segment and affected descendant labels."""
    operation: Literal["rename_label"] = Field("rename_label", description="Rename a final label segment and its descendants.",
        json_schema_extra={"x-display-name": "Rename Label", "x-category": "Labels"})
    new_label: str = Field(..., min_length=1, max_length=100)

    @field_validator("new_label")
    @classmethod
    def segment_value(cls, value):
        if "/" in value or _label_path("/" + value) != "/" + value:
            raise ValueError("Use one label name, not a path.")
        return value


class BrightcoveDeleteLabelConfig(BrightcoveExistingLabel):
    """Delete a label subtree; Brightcove asynchronously removes it from videos."""
    operation: Literal["delete_label"] = Field("delete_label", description="Delete a label subtree; removal from videos is asynchronous.",
        json_schema_extra={"x-display-name": "Delete Label", "x-category": "Labels"})


BrightcoveConfig = Annotated[Union[BrightcoveListVideosConfig, BrightcoveGetVideoConfig,
    BrightcoveCountConfig, BrightcoveCreateVideoConfig, BrightcoveUpdateVideoConfig,
    BrightcoveDeleteVideoConfig, BrightcoveListPlaylistsConfig, BrightcoveGetPlaylistConfig,
    BrightcoveListPlaylistVideosConfig, BrightcoveCreatePlaylistConfig, BrightcoveUpdatePlaylistConfig,
    BrightcoveDeletePlaylistConfig, BrightcoveListFoldersConfig, BrightcoveGetFolderConfig,
    BrightcoveListFolderVideosConfig, BrightcoveCreateFolderConfig, BrightcoveRenameFolderConfig,
    BrightcoveDeleteFolderConfig, BrightcoveAddFolderVideoConfig, BrightcoveRemoveFolderVideoConfig,
    BrightcoveFieldsConfig, BrightcoveListLabelsConfig, BrightcoveCreateLabelConfig,
    BrightcoveRenameLabelConfig, BrightcoveDeleteLabelConfig], Field(discriminator="operation")]


class BrightcoveNodeConfig(NodeConfig[BrightcoveConfig, BrightcoveClientCredential]):
    pass


async def _request(data, method, path, *, params=None, body=None, statuses=(200,), empty=False):
    data = _credential(data)
    if not _ready(data) or not path.startswith("/") or "?" in path or "#" in path or ".." in path or re.search(r"[\x00-\x1f]", path):
        raise ValueError("A current Brightcove token and supported account-relative path are required.")
    try:
        async with guarded_async_client( timeout=20.0, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, CMS_ROOT + data["account_id"] + path, params=params, json=body,
                headers={"Authorization": "Bearer " + data["access_token"], "Accept": "application/json"})
    except Exception:
        raise RuntimeError("Brightcove CMS request could not complete.") from None
    if response.status_code not in statuses:
        messages = {401: "Brightcove authentication is unverified; check client, expiry and account permissions.",
            403: "Brightcove access is unverified; the resource may be unavailable or permissions insufficient.",
            404: "Brightcove resource was not found in the selected account.",
            429: "Brightcove rate limit reached; retry later. No request was automatically retried."}
        raise RuntimeError(messages.get(response.status_code, "Brightcove returned an unexpected status.")) from None
    if empty:
        return {"http_status": response.status_code}
    if len(response.content) > 2_000_000:
        raise RuntimeError("Brightcove response exceeded the metadata size limit.")
    try:
        return response.json()
    except Exception:
        raise RuntimeError("Brightcove returned malformed JSON.") from None


def _count(value):
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if type(value) is not int or value < 0 or value > 1_000_000:
        raise RuntimeError("Brightcove returned an invalid catalog count.")
    return value


def _project(data, kind, account):
    if not isinstance(data, dict) or data.get("account_id") is not None and _id(data["account_id"]) != account:
        raise RuntimeError("Brightcove returned metadata from an unexpected account.")
    fields = {
        "video": ("id", "account_id", "name", "description", "long_description", "reference_id", "state", "complete", "duration", "created_at", "updated_at", "folder_id", "tags", "labels", "custom_fields"),
        "playlist": ("id", "account_id", "name", "description", "reference_id", "favorite", "type", "state", "created_at", "updated_at", "video_ids"),
        "folder": ("id", "account_id", "name", "created_at", "updated_at", "video_count"),
    }[kind]
    out = {key: data[key] for key in fields if key in data}
    out["id"] = _folder_id(data.get("id")) if kind == "folder" else _id(data.get("id"))
    for key, value in out.items():
        if key in {"tags", "labels", "video_ids"}:
            if value is not None and (not isinstance(value, list) or len(value) > 1000 or any(not isinstance(item, str) for item in value)):
                raise RuntimeError("Brightcove returned malformed metadata arrays.")
        elif key == "custom_fields":
            if value is not None and (not isinstance(value, dict) or len(value) > 100 or any(not isinstance(item, (str, type(None))) for item in value.values())):
                raise RuntimeError("Brightcove returned malformed custom fields.")
        elif value is not None and type(value) not in (str, int, float, bool):
            raise RuntimeError("Brightcove returned malformed metadata values.")
    if out.get("account_id") is not None:
        out["account_id"] = _id(out["account_id"])
    if out.get("video_ids") is not None:
        out["video_ids"] = [_id(item) for item in out["video_ids"]]
    if kind == "folder" and out.get("video_count") is not None:
        out["video_count"] = _count(out["video_count"])
    return out


async def _one(data, kind, identity):
    path = {"video": "/videos/", "playlist": "/playlists/", "folder": "/folders/"}[kind] + identity
    payload = await _request(data, "GET", path)
    if kind == "folder" and isinstance(payload, list) and len(payload) == 1:
        payload = payload[0]
    item = _project(payload, kind, data["account_id"])
    if item["id"] != identity:
        raise RuntimeError("Brightcove returned an unexpected resource ID.")
    return item


def _cursor(data, path, query, value=None, offset=None):
    anchor = {"version": 1, "account_id": data["account_id"], "client_id": data["client_id"],
        "permissions": data["permissions"], "path": path, "query": query}
    key = hashlib.sha256(data["client_secret"].encode()).digest()
    if value is not None:
        try:
            if not isinstance(value, str) or len(value) > 4096:
                raise ValueError()
            encoded, signature = value.split(".")
            expected = hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise ValueError()
            payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            actual_offset = payload.pop("offset")
            if payload != anchor or type(actual_offset) is not int or not 0 <= actual_offset <= 1_000_000:
                raise ValueError()
            return actual_offset
        except Exception:
            raise ValueError("Brightcove page token does not match this connection, account, parent and search.") from None
    encoded = base64.urlsafe_b64encode(json.dumps({**anchor, "offset": offset}, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    return encoded + "." + hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()


async def _page(data, path, kind, config, *, count_path=None, count_hint=None, local=False, search=None):
    query = {"limit": config.limit}
    if hasattr(config, "sort"):
        query["sort"] = config.sort
    if getattr(config, "q", None):
        query["q"] = config.q
    if kind == "video" and path.startswith("/playlists/"):
        query["include_details"] = "true"
    anchor = {**query, "local_search": search}
    offset = _cursor(data, path, anchor, value=config.page_token) if config.page_token else config.offset
    payload = await _request(data, "GET", path, params=None if local else {**query, "offset": offset})
    if kind == "label":
        if not isinstance(payload, dict) or _id(payload.get("account_id")) != data["account_id"] or not isinstance(payload.get("labels"), list):
            raise RuntimeError("Brightcove returned invalid account label metadata.")
        payload = payload["labels"]
    if not isinstance(payload, list) or len(payload) > (10_000 if kind == "label" else 1000 if local else config.limit):
        raise RuntimeError("Brightcove returned an invalid bounded metadata page.")
    total = len(payload) if local else _count(count_hint) if count_hint is not None else None
    selected = payload[offset:offset + config.limit] if local else payload
    items = [{"path": _label_path(item)} for item in selected] if kind == "label" else [_project(item, kind, data["account_id"]) for item in selected]
    if count_path:
        count = await _request(data, "GET", count_path, params={"q": query["q"]} if "q" in query else None)
        total = _count(count.get("count")) if isinstance(count, dict) else _count(None)
    more = offset + config.limit < total if total is not None else len(payload) == config.limit
    token = _cursor(data, path, anchor, offset=offset + config.limit) if more and offset + config.limit <= 1_000_000 else None
    if search:
        items = [item for item in items if search.casefold() in str(item.get("name") or item.get("path") or item.get("id")).casefold()]
    return {"items": items, "next_page_token": token, "reported_count": total,
        "offset": offset, "limit": config.limit, "snapshot": False}


class BrightcoveNode(WorkflowNode):
    integration_type = "automation-brightcove"
    connection_evidence = ConnectionEvidence(operation="list_videos", operation_arguments={"limit": 5},
        noun="videos", label_keys=("name",), identity_keys=(), proves="account")

    @classmethod
    def get_config_model(cls):
        return BrightcoveNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Mint a finite client-credentials token when needed, without a refresh token.

        Staging's loaders own access to saved credentials. These non-rotating
        client grants need no persisted token chain; minted tokens stay local.
        """
        data = _credential(credential_data)
        return data if _ready(data) else await _mint(data)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        data = await cls.freshen_credential(credential_data)
        _permission(data, "video")
        await _page(data, "/videos", "video", BrightcovePage(limit=1))
        return {"valid": True}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        data = await cls.freshen_credential(credential_data)
        if field_name not in {"video_id", "playlist_id", "folder_id", "folder_video_id", "label_path"}:
            raise ValueError("Unsupported Brightcove selector.")
        search = search.strip() if isinstance(search, str) and search.strip() else None
        if search and len(search) > 200:
            raise ValueError("Brightcove picker search is too long.")
        config = BrightcovePage(limit=50, page_token=page_token)
        if field_name == "folder_video_id":
            folder = _folder_id((context or {}).get("folder_id"))
            _permission(data, "video")
            parent = await _one(data, "folder", folder)
            result = await _page(data, "/folders/" + folder + "/videos", "video", config,
                count_hint=parent.get("video_count"), search=search)
        elif field_name == "playlist_id":
            _permission(data, "playlist")
            result = await _page(data, "/playlists", "playlist", config, count_path="/counts/playlists", search=search)
        elif field_name == "video_id":
            _permission(data, "video")
            result = await _page(data, "/videos", "video", config, count_path="/counts/videos", search=search)
        elif field_name == "folder_id":
            _permission(data, "video")
            result = await _page(data, "/folders", "folder", config, local=True, search=search)
        else:
            _permission(data, "video")
            result = await _page(data, "/labels", "label", config, local=True, search=search)
        return {"options": [{"value": item.get("id") or item["path"], "label": item.get("name") or item.get("path") or item["id"]}
                           for item in result["items"]], "next_page_token": result["next_page_token"]}

    async def execute(self, inputs):
        if not isinstance(self.config, BrightcoveNodeConfig) or not self.config.credentials:
            raise ValueError("Brightcove configuration and connection are required.")
        c = self.config.config
        self_data = self.config.credentials.model_dump(mode="json")
        # Check local capability before even minting a token.
        op = c.operation
        playlist = "playlist" in op
        resource = "playlist" if playlist else "video"
        action = "create" if op.startswith("create_") else "update" if op.startswith(("update_", "rename_", "add_", "remove_")) else "delete" if op.startswith("delete_") else "read"
        if op in {"create_label", "rename_label", "delete_label"}:
            action = "all"
        _permission(self_data, resource, action)
        data = await self.freshen_credential(self_data)
        _permission(data, resource, action)
        account = data["account_id"]
        if op == "get_catalog_counts":
            _permission(data, "playlist")
            videos = await _request(data, "GET", "/counts/videos")
            playlists = await _request(data, "GET", "/counts/playlists")
            return {"video_count": _count(videos.get("count") if isinstance(videos, dict) else None),
                "playlist_count": _count(playlists.get("count") if isinstance(playlists, dict) else None)}
        if op in {"list_videos", "list_playlists", "list_folders", "list_labels"}:
            plural = op.removeprefix("list_")
            kind = {"videos": "video", "playlists": "playlist", "folders": "folder", "labels": "label"}[plural]
            return await _page(data, "/" + plural, kind, c, count_path="/counts/" + plural if plural in {"videos", "playlists"} else None,
                local=plural in {"folders", "labels"})
        if op in {"get_video", "get_playlist", "get_folder"}:
            kind = op.removeprefix("get_")
            return {kind: await _one(data, kind, getattr(c, kind + "_id"))}
        if op in {"list_playlist_videos", "list_folder_videos"}:
            kind = "playlist" if op == "list_playlist_videos" else "folder"
            identity = getattr(c, kind + "_id")
            parent = await _one(data, kind, identity)
            return await _page(data, "/" + kind + "s/" + identity + "/videos", "video", c,
                count_path="/counts/playlists/" + identity + "/videos" if kind == "playlist" else None,
                count_hint=parent.get("video_count") if kind == "folder" else None)
        if op == "get_video_fields":
            payload = await _request(data, "GET", "/video_fields")
            if not isinstance(payload, dict):
                raise RuntimeError("Brightcove returned invalid custom-field metadata.")
            out = {}
            for group in ("custom_fields", "standard_fields"):
                rows = payload.get(group, [])
                if not isinstance(rows, list) or len(rows) > 1000 or any(not isinstance(row, dict) for row in rows):
                    raise RuntimeError("Brightcove returned invalid custom-field metadata.")
                out[group] = [{key: row[key] for key in ("id", "display_name", "description", "required", "type") if key in row and
                    (row[key] is None or type(row[key]) in (str, bool))} for row in rows]
            return out
        if op == "create_video_draft":
            body = c.model_dump(exclude={"operation", "labels"}, exclude_none=True)
            return {"video": _project(await _request(data, "POST", "/videos", body={**body, "state": "INACTIVE"}, statuses=(201,)), "video", account)}
        if op == "update_video_metadata":
            await _one(data, "video", c.video_id)
            body = c.model_dump(exclude={"operation", "video_id"}, exclude_none=True)
            return {"video": _project(await _request(data, "PATCH", "/videos/" + c.video_id, body=body), "video", account)}
        if op == "delete_video":
            await _one(data, "video", c.video_id)
            return {"deleted": True, **await _request(data, "DELETE", "/videos/" + c.video_id, statuses=(204,), empty=True)}
        if op in {"create_manual_playlist", "update_playlist", "delete_playlist"}:
            path = "/playlists"
            if op != "create_manual_playlist":
                existing = await _one(data, "playlist", c.playlist_id)
                path += "/" + c.playlist_id
                if op == "update_playlist" and c.video_ids is not None and existing.get("type") != "EXPLICIT":
                    raise ValueError("Only manual playlists accept replacement video membership.")
            if op == "delete_playlist":
                return {"deleted": True, **await _request(data, "DELETE", path, statuses=(204,), empty=True)}
            if c.video_ids:
                _permission(data, "video")
                for video in dict.fromkeys(c.video_ids):
                    await _one(data, "video", video)
            body = c.model_dump(exclude={"operation", "playlist_id"}, exclude_none=True)
            if op == "create_manual_playlist":
                body["type"] = "EXPLICIT"
            return {"playlist": _project(await _request(data, "POST" if op == "create_manual_playlist" else "PATCH", path,
                body=body, statuses=(201,) if op == "create_manual_playlist" else (200,)), "playlist", account)}
        if op in {"create_folder", "rename_folder", "delete_empty_folder"}:
            if op == "create_folder":
                return {"folder": _project(await _request(data, "POST", "/folders", body={"name": c.name}, statuses=(201,)), "folder", account)}
            existing = await _one(data, "folder", c.folder_id)
            if op == "rename_folder":
                return {"folder": _project(await _request(data, "PATCH", "/folders/" + c.folder_id, body={"name": c.name}), "folder", account)}
            if existing.get("name") != c.name or existing.get("video_count") != 0:
                raise ValueError("Delete requires the current folder name and an empty folder.")
            return {"deleted": True, **await _request(data, "DELETE", "/folders/" + c.folder_id, params={"name": c.name}, statuses=(201, 204), empty=True)}
        if op in {"add_video_to_folder", "remove_video_from_folder"}:
            folder = await _one(data, "folder", c.folder_id)
            video = await _one(data, "video", c.video_id)
            if op == "remove_video_from_folder" and video.get("folder_id") != c.folder_id:
                raise ValueError("The video is not in the selected folder.")
            return {"updated": True, **await _request(data, "PUT" if op.startswith("add_") else "DELETE",
                "/folders/" + c.folder_id + "/videos/" + c.video_id,
                body={"name": folder["name"]} if op.startswith("remove_") else None,
                statuses=(201, 204), empty=True)}
        if op == "create_label":
            payload = await _request(data, "POST", "/labels", body={"path": c.path}, statuses=(201,))
            if not isinstance(payload, dict):
                raise RuntimeError("Brightcove returned invalid label metadata.")
            return {"path": _label_path(payload.get("path"))}
        if op in {"rename_label", "delete_label"}:
            labels = await _request(data, "GET", "/labels")
            if not isinstance(labels, dict) or _id(labels.get("account_id")) != account or c.label_path not in [_label_path(path) for path in labels.get("labels", [])]:
                raise ValueError("The selected label does not exist in this account.")
            path = "/labels/by_path/" + quote(c.label_path, safe="/")
            if op == "delete_label":
                return {"deleted": True, **await _request(data, "DELETE", path, statuses=(204,), empty=True)}
            payload = await _request(data, "PATCH", path, body={"new_label": c.new_label}, statuses=(200, 201))
            if not isinstance(payload, dict):
                raise RuntimeError("Brightcove returned invalid label metadata.")
            return {"path": _label_path(payload.get("path")), "labels_updated": _count(payload["labels_updated"]) if "labels_updated" in payload else None}
        raise ValueError("Unsupported Brightcove operation.")
