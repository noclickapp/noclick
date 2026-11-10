"""JWX Management API v2: five closed, property-bound metadata GETs.

The published OAS 3.1.0/v0.2 is the contract. A supplied API secret is not a
player license key. Protected property reads prove reachability, not identity.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import math
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Any, Dict, Literal, Optional, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, WrapValidator, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.jwplayer.com/v2/sites"
FAMILY = "jwplayer_api_secret"
OPERATIONS = ("list_media", "get_media", "list_playlists", "get_playlist", "list_content_types")
_private_transport = contextvars.ContextVar("jwplayer_private_transport", default=False)


class JWPlayerError(ValueError):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _reference(value):
    return isinstance(value, str) and "{{" in value and "}}" in value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9]{8}", value.strip()):
        raise ValueError("Enter an eight-character alphanumeric JWX resource ID as text.")
    return value.strip()


def _pending(value, handler):
    return value if _reference(value) else handler(value)


ResourceID = Annotated[str, Field(pattern=r"^[A-Za-z0-9]{8}$", min_length=8, max_length=8), WrapValidator(_pending)]
Page = Annotated[int, Field(ge=1, le=1000000), WrapValidator(_pending)]
PageLength = Annotated[int, Field(ge=1, le=100), WrapValidator(_pending)]
LocalLimit = Annotated[int, Field(ge=1, le=100), WrapValidator(_pending)]


class JWPlayerAPISecretCredential(BaseModel):
    credential_type: Literal["jwplayer_api_secret"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_secret: str = Field(..., description="Existing Management API v2 secret, sent only in the Bearer header. Player license keys are different.", json_schema_extra={"ui:widget": "password"})
    site_id: str = Field(..., description="Exact eight-character property ID that bounds every read. This is not an account or principal identity.")
    model_config = ConfigDict(title="JWX Management API Secret", extra="ignore", json_schema_extra={
        "x-credential-url": "https://dashboard.jwplayer.com/account/developer-tools/management-api",
        "x-credential-instructions": "Supply an existing Management API v2 secret and property ID. NoClick does not issue, rotate or exchange tokens. API entitlement must be confirmed with your JWX account.",
    })

    @field_validator("api_secret", mode="before")
    @classmethod
    def secret(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter a text Management API secret.")
        value = clean_secret(value, field_name="API secret")
        if not value or len(value) > 8192 or _reference(value) or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Enter a valid Management API secret without whitespace or references.")
        return value

    @field_validator("site_id", mode="before")
    @classmethod
    def property_id(cls, value):
        return _id(value)


class _Common(BaseModel):
    include_names: bool = Field(False, description="Include media/playlist titles or content-type display names. Names can reveal business resources.")
    model_config = ConfigDict(extra="ignore")

    @field_validator("media_id", "playlist_id", mode="before", check_fields=False)
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) and not _reference(value) else value


class _Page(_Common):
    page: Page = Field(1, description="One numbered provider page. The native page-number bound is 1,000,000; no provider maximum is inferred.")
    page_length: PageLength = Field(20, description="One provider page, capped locally at 100 rows. No pagination loop or arbitrary query is used.")


class ListMediaConfig(_Page):
    """Read one property media metadata page without media URLs or content."""
    operation: Literal["list_media"] = "list_media"


class GetMediaConfig(_Common):
    """Read the selected property's exact media ID and processing metadata."""
    operation: Literal["get_media"] = "get_media"
    media_id: ResourceID = Field(..., description="Media ID under the credential's property. Enter an explicit ID or a workflow reference.", json_schema_extra={"x-resource-type": "jwplayer_media_id"})


class ListPlaylistsConfig(_Page):
    """Read one property playlist metadata page; omit members and delivery links."""
    operation: Literal["list_playlists"] = "list_playlists"


class GetPlaylistConfig(_Common):
    operation: Literal["get_playlist"] = "get_playlist"
    playlist_id: ResourceID = Field(..., description="Playlist ID under the credential's property. Enter an explicit ID or a workflow reference.", json_schema_extra={"x-resource-type": "jwplayer_playlist_id"})


class ListContentTypesConfig(_Common):
    """Read bounded content-type IDs/classification metadata, excluding section definitions."""
    operation: Literal["list_content_types"] = "list_content_types"
    limit: LocalLimit = Field(100, description="Local result cap. This route documents no request paging parameters; completeness remains unknown.")


JWPlayerOperation = Annotated[Union[ListMediaConfig, GetMediaConfig, ListPlaylistsConfig, GetPlaylistConfig, ListContentTypesConfig], Field(discriminator="operation")]


class JWPlayerNodeConfig(NodeConfig[JWPlayerOperation, JWPlayerAPISecretCredential]):
    pass


def _raw_guard(data):
    if not isinstance(data, dict):
        raise ValueError("JWX configuration must be an object.")
    ids = data.get("credentialIds") or {}
    if not isinstance(ids, dict) or any(k not in (FAMILY, "credential_type") for k in ids) or ids.get("credential_type") not in (None, FAMILY) or data.get("credential_type") not in (None, FAMILY):
        raise ValueError("Select the native JWX Management API credential family.")
    chosen, mapped = data.get("credential_id"), ids.get(FAMILY)
    for value in (chosen, mapped):
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("Select a saved JWX credential UUID.")
            try:
                UUID(value)
            except (ValueError, TypeError):
                raise ValueError("Select a saved JWX credential UUID.") from None
    if chosen and mapped and chosen != mapped:
        raise ValueError("JWX credential selections disagree.")
    creds = data.get("credentials")
    if creds is not None:
        if not isinstance(creds, dict) or creds.get("credential_type") not in (None, FAMILY):
            raise ValueError("Foreign credential data cannot authenticate JWX.")
        if (chosen or mapped or creds.get("token_version") is not None or creds.get("updated_at") is not None) and creds.get("credential_type") != FAMILY:
            raise ValueError("Stored JWX credentials require their native family tag.")
        try:
            JWPlayerAPISecretCredential.model_validate(creds)
        except Exception:
            raise ValueError("Check the JWX API secret and property ID fields.") from None
    inner = data.get("config") or {}
    if not isinstance(inner, dict):
        raise ValueError("JWX operation configuration must be an object.")
    selected = ("media_id",) if inner.get("operation") == "get_media" else ("playlist_id",) if inner.get("operation") == "get_playlist" else ()
    for key in selected:
        value = inner.get(key)
        if value not in (None, "") and not _reference(value):
            _id(value)
    paging = ("page", "page_length") if inner.get("operation") in ("list_media", "list_playlists") else ("limit",) if inner.get("operation") == "list_content_types" else ()
    for key in paging:
        value = inner.get(key)
        if value not in (None, "") and not _reference(value) and type(value) is not int:
            raise ValueError("JWX paging values must be integers.")
    if "include_names" in inner and inner["include_names"] not in (None, "") and type(inner["include_names"]) is not bool:
        raise ValueError("Include names must be a checkbox value.")


class _TransportFilter(logging.Filter):
    def filter(self, record):
        return not _private_transport.get()


@contextmanager
def _quiet_transport():
    token = _private_transport.set(True)
    filters = []
    try:
        for name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
            logger = logging.getLogger(name)
            f = _TransportFilter()
            logger.addFilter(f)
            filters.append((logger, f))
        yield
    finally:
        for logger, f in filters:
            logger.removeFilter(f)
        _private_transport.reset(token)


class JWPlayerNode(WorkflowNode):
    integration_type = "automation-jwplayer"
    credential_provider_labels = {"jwplayer": "Jwplayer Account"}
    connection_evidence = ConnectionEvidence(operation="list_media", noun="property media", label_keys=("id",), proves="reachability")
    scope_registry = ScopeRegistry("jwplayer", {op: ScopeRequirement(scopes=(), credential_types=(FAMILY,)) for op in OPERATIONS})

    @classmethod
    def get_config_model(cls):
        return JWPlayerNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        _raw_guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _raw_guard(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    def _selected_id(self):
        _raw_guard(self.node_data)
        return self.node_data.get("credential_id") or (self.node_data.get("credentialIds") or {}).get(FAMILY)

    def _snapshot(self):
        return hashlib.sha256(json.dumps({"actor": self.user_id, "org": self.organization_id, "workflow": self.workflow_id,
            "raw": {k: self.node_data.get(k) for k in ("credentials", "credential_id", "credentialIds", "config")},
            "typed": self.config.model_dump(mode="json")}, sort_keys=True, default=str).encode()).hexdigest()

    def _unchanged(self):
        if self._snapshot() != self._frame:
            raise JWPlayerError("JWX actor, credential or resource selection changed. Retry with the current selection.")

    async def run(self, inputs):
        cid = self._selected_id()
        self.node_data = dict(self.node_data)
        if cid:
            self.node_data["credential_id"] = cid
        self._frame = self._snapshot()
        return await super().run(inputs)

    async def _fresh(self):
        self._unchanged()
        attached = self.config.credentials
        if attached is None:
            raise JWPlayerError("Select a JWX Management API secret and property ID.")
        cid = self._selected_id()
        if not cid:
            credential = attached
            raw = self.node_data.get("credentials")
            if isinstance(raw, dict) and JWPlayerAPISecretCredential.model_validate(raw) != attached:
                raise JWPlayerError("JWX unsaved credential shaping changed; parse the current selection.")
            binding = (None, credential.site_id, credential.api_secret)
        else:
            from repositories.organization import OrgRepo
            from repositories.jwplayer_authority import current_jwplayer_row
            from utils.credentials import get_workflow_owner_id, is_credential_authorized_for_workflow
            from utils.database_pool import get_native_pool
            from utils.encryption import get_encryption

            if not self.user_id:
                raise JWPlayerError("JWX saved credentials need the current authenticated actor.")
            pool = get_native_pool()
            async with pool.acquire() as conn:
                org_id = await OrgRepo(pool).get_primary_org_id(conn, self.user_id)
                self._unchanged()
                row = await current_jwplayer_row(conn, cid, self.user_id, org_id)
            self._unchanged()
            if not row and self.workflow_id:
                owner = await get_workflow_owner_id(pool, self.workflow_id)
                self._unchanged()
                authorized = owner and owner != self.user_id and await is_credential_authorized_for_workflow(pool, self.workflow_id, cid)
                self._unchanged()
                if authorized:
                    async with pool.acquire() as conn:
                        row = await current_jwplayer_row(conn, cid, owner, org_id)
                    self._unchanged()
            if not row or str(row.get("id")) != cid or row.get("credential_type") != FAMILY or row.get("revoked_at") is not None:
                raise JWPlayerError("Current JWX credential is missing, inaccessible, revoked or of another family.")
            raw = get_encryption().decrypt_credential(row["credential"])
            if not isinstance(raw, dict) or raw.get("credential_type") not in (None, FAMILY):
                raise JWPlayerError("Current JWX row contains foreign credential data.")
            try:
                credential = JWPlayerAPISecretCredential.model_validate(dict(raw, credential_type=FAMILY))
            except Exception:
                raise JWPlayerError("Current JWX credential has invalid secret or property fields.") from None
            if credential.site_id != attached.site_id:
                raise JWPlayerError("JWX property binding changed; reselect the current credential.")
            binding = (cid, str(row["owner_id"]), str(row.get("organization_id")), org_id,
                row.get("token_version"), str(row.get("updated_at")), credential.site_id, credential.api_secret)
        if self._binding is None:
            self._binding = binding
        elif self._binding != binding:
            raise JWPlayerError("JWX credential access or version changed during this read.")
        self._unchanged()
        return credential

    async def _request(self, route, params=None):
        if route in ("/media/", "/playlists/"):
            allowed = {"page", "page_length"}
        elif route == "/content_type_schemas/" or re.fullmatch(r"/(?:media|playlists)/[A-Za-z0-9]{8}/", route):
            allowed = set()
        else:
            raise JWPlayerError("Unsupported JWX metadata route.")
        params = dict(params or {})
        if not set(params) <= allowed or any(type(v) is not int or v < 1 for v in params.values()) or params.get("page_length", 1) > 100 or params.get("page", 1) > 1000000:
            raise JWPlayerError("Unsupported JWX request parameters.")
        credential = await self._fresh()
        path = "/v2/sites/" + credential.site_id + route

        async def before_send(request):
            current = await self._fresh()
            if request.url.scheme != "https" or request.url.host != "api.jwplayer.com" or request.url.port not in (None, 443) or request.url.path != path or sorted(request.url.params.multi_items()) != sorted((k, str(v)) for k, v in params.items()):
                raise JWPlayerError("JWX request origin, property or parameters changed.")
            request.headers["Authorization"] = "Bearer " + current.api_secret

        try:
            with _quiet_transport():
                async with guarded_async_client(timeout=20, trust_env=False, follow_redirects=False, event_hooks={"request": [before_send]}) as client:
                    async with client.stream("GET", BASE_URL + "/" + credential.site_id + route, params=params, headers={"Accept": "application/json", "Authorization": "Bearer " + credential.api_secret}) as response:
                        status = response.status_code
                        if status != 200:
                            raise JWPlayerError({400: "JWX rejected the metadata parameters.", 401: "JWX rejected the Management API secret.", 403: "JWX permission or property access is missing.", 404: "JWX property resource was not found.", 429: "JWX rate limit reached; retry later."}.get(status, "JWX did not return a completed metadata read."), status)
                        if "json" not in response.headers.get("content-type", "").lower():
                            raise JWPlayerError("JWX returned unsupported response media.")
                        body = bytearray()
                        async for part in response.aiter_bytes():
                            body.extend(part)
                            if len(body) > 4 * 1024 * 1024:
                                raise JWPlayerError("JWX response exceeded the metadata size bound.")
                        try:
                            data = json.loads(body, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
                        except (ValueError, RecursionError):
                            raise JWPlayerError("JWX returned invalid JSON metadata.") from None
            await self._fresh()
            pending, visited = [data], 0
            while pending:
                value = pending.pop(); visited += 1
                if visited > 100000:
                    raise JWPlayerError("JWX JSON exceeded the metadata complexity bound.")
                if isinstance(value, str) and credential.api_secret in value:
                    raise JWPlayerError("JWX reflected credential material; response withheld.")
                if isinstance(value, dict):
                    pending.extend(value.keys()); pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
            if not isinstance(data, dict):
                raise JWPlayerError("JWX returned an unsupported metadata envelope.")
            return data
        except httpx.HTTPError:
            raise JWPlayerError("JWX metadata transport failed; no response is confirmed.") from None

    @staticmethod
    def _count(value):
        if type(value) is not int or value < 0 or value > 10**15:
            raise JWPlayerError("JWX returned an invalid metadata count.")
        return value

    @staticmethod
    def _text(data, key, result, *, timestamp=False, bound=5000):
        value = data.get(key)
        if value is None:
            return
        if not isinstance(value, str) or len(value) > bound or any(ord(c) < 32 for c in value) or "://" in value:
            raise JWPlayerError("JWX returned invalid text metadata.")
        if timestamp:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
                raise JWPlayerError("JWX returned invalid timestamp metadata.")
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise JWPlayerError("JWX returned invalid timestamp metadata.") from None
        result[key] = value

    def _project(self, row, kind):
        if not isinstance(row, dict):
            raise JWPlayerError("JWX returned an unsupported resource envelope.")
        try:
            resource_id = row.get("id")
            if not isinstance(resource_id, str) or not re.fullmatch(r"[A-Za-z0-9]{8}", resource_id):
                raise ValueError("Invalid response ID")
            result = {"id": resource_id}
        except ValueError:
            raise JWPlayerError("JWX returned an invalid resource ID.") from None
        for key in ("created", "last_modified"):
            self._text(row, key, result, timestamp=True, bound=64)
        fields = {"media": {"status": ("created", "processing", "ready", "updating", "failed"), "media_type": ("audio", "video"), "hosting_type": ("external", "hosted", "renditions")},
            "playlist": {"playlist_type": ("article_matching", "dynamic", "manual", "search", "watchlist")}}.get(kind, {})
        for key, values in fields.items():
            if row.get(key) is not None:
                if row[key] not in values:
                    raise JWPlayerError("JWX returned a resource classification outside the published OAS enum.")
                result[key] = row[key]
        if kind == "media" and row.get("duration") is not None:
            duration = row["duration"]
            if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= 10**10:
                raise JWPlayerError("JWX returned invalid duration metadata.")
            result["duration"] = duration
        metadata = row.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise JWPlayerError("JWX returned unsupported resource metadata.")
        if kind == "content_type" and isinstance(metadata, dict) and metadata.get("hosting_type") is not None:
            if metadata["hosting_type"] not in ("external", "hosted", "ott_data", "live_bcl", "renditions"):
                raise JWPlayerError("JWX returned an unsupported content-type hosting classification.")
            result["hosting_type"] = metadata["hosting_type"]
        if self.config.config.include_names and isinstance(metadata, dict):
            self._text(metadata, "display_name" if kind == "content_type" else "title", result, bound=256 if kind == "playlist" else 5000)
        return result

    def _rows(self, data, key, *, bound):
        if not isinstance(data, dict) or not isinstance(data.get(key), list) or len(data[key]) > bound:
            raise JWPlayerError("JWX returned an unsupported collection envelope or exceeded its native bound.")
        rows = data[key]
        ids = []
        for row in rows:
            try:
                resource_id = row.get("id") if isinstance(row, dict) else None
                if not isinstance(resource_id, str) or not re.fullmatch(r"[A-Za-z0-9]{8}", resource_id):
                    raise ValueError("Invalid response ID")
                ids.append(resource_id)
            except ValueError:
                raise JWPlayerError("JWX returned an invalid collection resource ID.") from None
        if len(ids) != len(set(ids)):
            raise JWPlayerError("JWX returned duplicate collection resource IDs.")
        return rows

    def _page(self, data, *, numbered):
        result = {"completion": "unknown"}
        for key in ("page", "page_length", "total"):
            if data.get(key) is not None:
                result["provider_" + key] = self._count(data[key])
        if numbered:
            config = self.config.config
            result.update(requested_page=config.page, requested_page_length=config.page_length)
            if result.get("provider_page", config.page) != config.page or result.get("provider_page_length", config.page_length) != config.page_length:
                raise JWPlayerError("JWX returned another numbered page.")
        return result

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        _raw_guard(self.node_data)
        self._frame = getattr(self, "_frame", self._snapshot())
        self._binding = None
        config = self.config.config
        if any(_reference(value) for value in config.model_dump().values()):
            raise JWPlayerError("Resolve JWX resource and page references before execution.")
        credential = await self._fresh()
        operation = config.operation
        if operation in ("list_media", "list_playlists", "list_content_types"):
            key, kind, route = {"list_media": ("media", "media", "/media/"), "list_playlists": ("playlists", "playlist", "/playlists/"), "list_content_types": ("content_type_schemas", "content_type", "/content_type_schemas/")}[operation]
            numbered = operation != "list_content_types"
            data = await self._request(route, {"page": config.page, "page_length": config.page_length} if numbered else None)
            rows = self._rows(data, key, bound=config.page_length if numbered else 10000)
            selected = rows if numbered else rows[:config.limit]
            result = {key: [self._project(row, kind) for row in selected], "site_id": credential.site_id,
                "returned_count": len(selected), "locally_truncated": len(selected) < len(rows), **self._page(data, numbered=numbered)}
        else:
            resource_id = _id(config.media_id if operation == "get_media" else config.playlist_id)
            kind, route = ("media", "/media/") if operation == "get_media" else ("playlist", "/playlists/")
            data = await self._request(route + resource_id + "/")
            projected = self._project(data, kind)
            if projected["id"] != resource_id:
                raise JWPlayerError("JWX returned another property resource.")
            result = {kind: projected, "site_id": credential.site_id}
        await self._fresh()
        self._unchanged()
        return {"success": True, "data": result}
