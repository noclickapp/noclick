"""Two closed Immich album metadata GETs; current prerelease server parity unverified."""
from dataclasses import dataclass, field
import ipaddress
import json
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator, model_serializer
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from repositories.immich_credentials import fetch_snapshot
from utils.ssrf import allow_private_hosts, guarded_async_client, normalize_https_origin

TYPE = "immich_api_key"
MAX_BYTES = 2 * 1024 * 1024
MAX_OUTPUT = 100
OPERATIONS = {"list_albums", "get_album"}
MAX_COUNT = 9007199254740991  # Documented AlbumResponseDto.assetCount maximum.
UUID4_PATTERN = r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$"
ID = Annotated[StrictStr, Field(pattern=UUID4_PATTERN)]


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(UUID4_PATTERN, value):
        raise ValueError("Immich requires the exact current UUIDv4 album ID")
    return value


def scalar_text(value):
    if not isinstance(value, str) or len(value) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Immich returned malformed scalar text")
    return value


class ImmichAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, title="Immich API Key", json_schema_extra={"x-credential-url": "https://docs.immich.app/api/"})
    credential_type: Literal["immich_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    instance_origin: str = Field(..., repr=False, title="Instance HTTPS Origin", description="One public HTTPS origin, with no credentials/path/query/fragment. API paths are fixed /api. Current master OAS3.0.0/version3.3.0-rc.0 parity with your installed server is unverified; no fallback.")
    api_key: str = Field(..., min_length=1, max_length=8192, repr=False, title="Existing API Key", description="Supplied existing x-api-key header only. Both selected documented operations require album.read; current key kind, permissions and principal remain unverified. No token issuance, login or refresh.", json_schema_extra={"ui:widget": "password"})

    @model_serializer(mode="wrap")
    def canonical(self, handler):
        return {**handler(self), "credential_type": TYPE}

    @field_validator("instance_origin", mode="before")
    @classmethod
    def origin(cls, value):
        try:
            if not isinstance(value, str): raise ValueError()
            normalized = normalize_https_origin(value, field_name="Immich instance")
            host = urlsplit(normalized).hostname
            if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")): raise ValueError()
            try: address = ipaddress.ip_address(host)
            except ValueError: address = None
            if address is not None and not address.is_global: raise ValueError()
            return normalized
        except ValueError:
            raise ValueError("Supply one public HTTPS Immich origin without paths or credentials") from None

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply the existing Immich API key without whitespace")
        return value


def guard(data):
    if not isinstance(data, dict) or data.get("credential_type") != TYPE:
        raise ValueError("Connect a typed Immich API key")
    try:
        return ImmichAPIKeyCredential.model_validate({k: v for k, v in data.items() if k not in {"_immich_reader", "token_version", "updated_at"}})
    except ValueError:
        raise ValueError("Immich credential shape is invalid; reconnect it") from None


def authority(value):
    return value.credential_type, value.instance_origin, value.api_key

async def current(credential_id, user_id, organization_id=None, workflow_id=None, *, pool=None):
    if not user_id:
        raise ValueError("Stored Immich credentials require a caller")
    from utils.database_pool import get_native_pool
    from utils.credentials import get_workflow_owner_id, is_credential_authorized_for_workflow
    from utils.encryption import get_encryption
    pool = pool or get_native_pool()
    row = await fetch_snapshot(pool, credential_id, user_id, organization_id)
    if row is None and workflow_id:
        owner = await get_workflow_owner_id(pool, workflow_id)
        if owner and str(owner) != str(user_id) and await is_credential_authorized_for_workflow(pool, workflow_id, credential_id):
            row = await fetch_snapshot(pool, credential_id, owner, organization_id, workflow_id=workflow_id)
    if row is None or row["revoked_at"] is not None or row["credential_type"] != TYPE or not row["owner_id"] or type(row["token_version"]) is not int or row["token_version"] < 0:
        raise ValueError("Immich credential is unavailable or has the wrong type/version")
    try:
        data = get_encryption().decrypt_credential(row["credential"])
    except Exception:
        raise ValueError("Immich credential cannot be read") from None
    if not isinstance(data, dict) or data.get("credential_type") != row["credential_type"]:
        raise ValueError("Immich saved credential type does not match its row")
    return guard(data), str(row["owner_id"]), row["token_version"]


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
        value, owner, version = await current(self.credential_id, self.user_id, self.organization_id, self.workflow_id, pool=self.pool)
        if self.expected is not None and authority(value) != self.expected:
            raise ValueError("Immich cached credential changed; reload it")
        binding = (owner, version, *authority(value))
        if self.anchor is not None and binding != self.anchor:
            raise ValueError("Immich saved credential changed during this call")
        self.anchor = binding
        return value


def op(value, title):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Metadata", "x-is-trigger": False})


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    include_names: StrictBool = Field(False, title="Include Album Names", description="Opt in to albumName only. Assets, media, users, sharing, descriptions and URLs are omitted.")


class ListAlbums(Input):
    operation: Literal["list_albums"] = op("list_albums", "List Album Metadata")


class GetAlbum(Input):
    operation: Literal["get_album"] = op("get_album", "Get Album Metadata")
    album_id: ID = Field(..., title="Album", description="Exact current UUIDv4 album ID from the bounded catalog. Case is preserved; catalog/detail/catalog witnesses access, not ownership.", json_schema_extra={"x-resource-type": "immich_album", "x-dynamic-options": {"field_name": "album_id", "searchable": True, "allow_custom": True}})


Config = Annotated[Union[ListAlbums, GetAlbum], Field(discriminator="operation")]


class ImmichNodeConfig(NodeConfig[Config, ImmichAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class PrivateHeaders(dict):
    def __repr__(self): return "<private Immich API-key headers>"
    __str__ = __repr__


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("Repeated Immich metadata field")
        result[key] = value
    return result


def invalid_number(_value): raise ValueError("Nonfinite Immich number")


async def request(value, resource, *, album_id=None, reader=None):
    if resource == "albums" and album_id is None: endpoint = "/albums"
    elif resource == "album": endpoint = "/albums/" + quote(identifier(album_id), safe="")
    else: raise ValueError("Unsupported Immich metadata operation")
    if reader: value = await reader.read()
    headers = PrivateHeaders({"x-api-key": value.api_key, "Accept": "application/json", "Cache-Control": "no-store"})
    status = None
    try:
        try:
            if allow_private_hosts():
                raise ValueError("Immich requires the public-address SSRF guard")
            async with guarded_async_client(timeout=12, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", value.instance_origin + "/api" + endpoint, headers=headers) as response:
                    status = response.status_code
                    if status != 200 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError("Immich metadata status/format unavailable")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES: raise ValueError("Immich metadata exceeds local 2MiB bound")
            payload = json.loads(raw, object_pairs_hook=unique_json, parse_constant=invalid_number)
            if not isinstance(payload, (dict, list)): raise ValueError("Immich metadata requires an album array or object")
            return payload
        except Exception:
            suffix = f" (HTTP {status})" if type(status) is int and 100 <= status <= 599 else ""
            raise ValueError("Immich album metadata could not be established" + suffix + "; key/instance/version/permissions/service cause unknown") from None
    finally:
        if reader: await reader.read()


def record(row, *, names=False):
    if not isinstance(row, dict): raise ValueError("Immich metadata requires an album object")
    result = {"id": identifier(row.get("id"))}
    count = row.get("assetCount")
    if type(count) is not int or not 0 <= count <= MAX_COUNT:
        raise ValueError("Immich assetCount requires the documented nonnegative integer range")
    result["assetCount"] = count
    for key in ("createdAt", "updatedAt"):
        result[key] = scalar_text(row.get(key))
    active = row.get("isActivityEnabled")
    if type(active) is not bool: raise ValueError("Immich isActivityEnabled requires a boolean")
    result["isActivityEnabled"] = active
    if names: result["albumName"] = scalar_text(row.get("albumName"))
    return result


def catalog(payload):
    if not isinstance(payload, list): raise ValueError("Immich requires the documented bare album array")
    ids = [record(row)["id"] for row in payload]
    if len(ids) != len(set(ids)): raise ValueError("Immich catalog repeated an album ID")
    return payload


def result_page(payload, *, names=False):
    rows = catalog(payload)
    return {"items": [record(r, names=names) for r in rows[:MAX_OUTPUT]], "completion_verified": False, "truncated": len(rows) > MAX_OUTPUT, "local_output_limit": MAX_OUTPUT, "snapshot_verified": False, "principal_identity_verified": False, "ownership_verified": False}


async def witness_album(value, selected, *, reader=None):
    rows = catalog(await request(value, "albums", reader=reader))
    if len(rows) > MAX_OUTPUT: raise ValueError("Immich album witness exceeds local 100 catalog bound")
    if not any(r["id"] == selected for r in rows): raise ValueError("Immich selected album unavailable in the current catalog")
    return rows


class ImmichNode(WorkflowNode):
    integration_type = "automation-immich"
    credential_provider_labels = {"immich": "Immich Account"}
    auto_select_credential = False
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_albums", noun="key-visible album metadata", proves="reachability")

    @classmethod
    def get_config_model(cls): return ImmichNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._resolve_current_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id
        )

    @classmethod
    async def _resolve_current_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=None):
        value = guard(credential_data)
        if not credential_id: return value.model_dump()
        if not user_id: raise ValueError("Stored Immich credentials require a caller")
        reader = Reader(credential_id, user_id, organization_id, workflow_id, pool, expected=authority(value))
        fresh = await reader.read()
        return {**fresh.model_dump(), "_immich_reader": reader}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        value = guard(credential_data); reader = credential_data.get("_immich_reader")
        if reader is not None and not isinstance(reader, Reader): raise ValueError("Invalid Immich current-row reader")
        try:
            if field_name != "album_id" or page_token is not None: raise ValueError("Immich has one album picker and no documented paging")
            search = "" if search is None else search
            if not isinstance(search, str) or len(search) > 256: raise ValueError("Supply a bounded local Immich picker search")
            rows = catalog(await request(value, "albums", reader=reader))
            if len(rows) > MAX_OUTPUT: raise ValueError("Immich picker exceeds local 100 output bound; completeness remains unknown")
            names = (context or {}).get("include_names") is True
            options = []
            for row in rows:
                label = scalar_text(row.get("albumName")) if names else "Album " + row["id"]
                if search.casefold() in (row["id"] + " " + label).casefold(): options.append({"value": row["id"], "label": label})
            return {"options": options, "next_page_token": None}
        finally:
            if reader: await reader.read()

    async def execute(self, inputs):
        cfg = self.config.config
        raw = self.node_data.get("credentials") or (self.config.credentials.model_dump() if self.config.credentials is not None else None)
        data = await self._resolve_current_credential(raw, credential_id=self.node_data.get("credential_id"), user_id=self.user_id, workflow_id=self.workflow_id, organization_id=self.organization_id, pool=self.node_data.get("_approval_pool"))
        value, reader = guard(data), data.get("_immich_reader")
        try:
            if cfg.operation == "list_albums": return result_page(await request(value, "albums", reader=reader), names=cfg.include_names)
            if cfg.operation != "get_album": raise ValueError("Unsupported Immich metadata operation")
            selected = identifier(cfg.album_id)
            await witness_album(value, selected, reader=reader)
            album = record(await request(value, "album", album_id=selected, reader=reader), names=cfg.include_names)
            if album["id"] != selected: raise ValueError("Immich returned a different album ID")
            await witness_album(value, selected, reader=reader)
            return album
        finally:
            if reader: await reader.read()
