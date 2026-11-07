"""Four closed Audiobookshelf library/author metadata reads.

Current catalogs witness access, never actor or ownership. No media or control.
"""
from dataclasses import dataclass, field
import ipaddress
import json
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator, model_serializer
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import allow_private_hosts, guarded_async_client, normalize_https_origin

from repositories.credentials import credential_access_predicate


async def fetch_snapshot(pool, credential_id, user_id, organization_id=None, *, workflow_id=None):
    workflow_guard = "" if workflow_id is None else """
      AND EXISTS (SELECT 1 FROM workflows w
          JOIN workflow_authorized_credentials a ON a.workflow_id = w.id
          WHERE w.id = $4 AND w.owner_id = $2 AND a.credential_id = c.id)
    """
    args = [credential_id, user_id, organization_id]
    if workflow_id is not None:
        args.append(workflow_id)
    async with pool.acquire() as conn:
        return await conn.fetchrow(f"""
          SELECT c.credential, c.credential_type, c.owner_id, c.token_version, c.revoked_at
          FROM credentials c WHERE c.id = $1
          AND {credential_access_predicate()} {workflow_guard}
        """, *args)


TYPE = "audiobookshelf_api_key"
MAX_BYTES = 2 * 1024 * 1024
MAX_OUTPUT = 100
OPERATIONS = {"list_libraries", "get_library", "list_library_authors", "get_author"}
ID = Annotated[StrictStr, Field(min_length=36, max_length=36)]


def identifier(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}", value) is None:
        raise ValueError("Audiobookshelf requires an exact UUID string resource ID")
    return value


def scalar_text(value):
    if not isinstance(value, str) or len(value) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Audiobookshelf returned malformed scalar text")
    return value


class AudiobookshelfAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, title="Audiobookshelf API Key", json_schema_extra={"x-credential-url": "https://audiobookshelf.org/docs/documentation/server-management/api-keys/"})
    credential_type: Literal["audiobookshelf_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    instance_origin: str = Field(..., repr=False, title="Instance HTTPS Origin", description="One public HTTPS origin, with no credentials/path/query/fragment. API paths are fixed /api. Hosted/self-hosted instance version parity is unverified.")
    api_key: str = Field(..., min_length=1, max_length=8192, repr=False, title="Existing Server API Key", description="Supplied server API key from server 2.26.0 or later, Bearer header only. No legacy user API token, login, parsing, issuance or refresh.", json_schema_extra={"ui:widget": "password"})

    @model_serializer(mode="wrap")
    def canonical(self, handler):
        return {**handler(self), "credential_type": TYPE}

    @field_validator("instance_origin", mode="before")
    @classmethod
    def origin(cls, value):
        try:
            if not isinstance(value, str): raise ValueError()
            normalized = normalize_https_origin(value, field_name="Audiobookshelf instance")
            host = urlsplit(normalized).hostname
            if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")): raise ValueError()
            try: address = ipaddress.ip_address(host)
            except ValueError: address = None
            if address is not None and not address.is_global: raise ValueError()
            return normalized
        except ValueError:
            raise ValueError("Supply one public HTTPS Audiobookshelf origin without paths or credentials") from None

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply the existing Audiobookshelf server API key without whitespace")
        return value


def guard(data):
    if not isinstance(data, dict) or data.get("credential_type") != TYPE:
        raise ValueError("Connect a typed Audiobookshelf server API key")
    try:
        return AudiobookshelfAPIKeyCredential.model_validate({k: v for k, v in data.items() if k not in {"_audiobookshelf_reader", "token_version", "updated_at"}})
    except ValueError:
        raise ValueError("Audiobookshelf credential shape is invalid; reconnect it") from None


def authority(value):
    return value.credential_type, value.instance_origin, value.api_key

async def current(credential_id, user_id, organization_id=None, workflow_id=None, *, pool=None):
    if not user_id:
        raise ValueError("Stored Audiobookshelf credentials require a caller")
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
        raise ValueError("Audiobookshelf credential is unavailable or has the wrong type/version")
    try:
        data = get_encryption().decrypt_credential(row["credential"])
    except Exception:
        raise ValueError("Audiobookshelf credential cannot be read") from None
    if not isinstance(data, dict) or data.get("credential_type") != row["credential_type"]:
        raise ValueError("Audiobookshelf saved credential type does not match its row")
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
            raise ValueError("Audiobookshelf cached credential changed; reload it")
        binding = (owner, version, *authority(value))
        if self.anchor is not None and binding != self.anchor:
            raise ValueError("Audiobookshelf saved credential changed during this call")
        self.anchor = binding
        return value


def op(value, title):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Metadata", "x-is-trigger": False})


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    include_names: StrictBool = Field(False, title="Include Names", description="Opt in to library/author names. Media, filesystem paths, author identifiers, images and permission metadata are omitted.")


class ListLibraries(Input):
    operation: Literal["list_libraries"] = op("list_libraries", "List Library Metadata")


class LibraryInput(Input):
    library_id: ID = Field(..., title="Library", description="Exact UUID from the current key-visible library catalog; access does not prove ownership.", json_schema_extra={"x-resource-type": "audiobookshelf_library", "x-dynamic-options": {"field_name": "library_id", "searchable": True, "allow_custom": True}})

    @field_validator("library_id", mode="before")
    @classmethod
    def exact_library(cls, value): return identifier(value)


class GetLibrary(LibraryInput):
    operation: Literal["get_library"] = op("get_library", "Get Library Metadata")


class ListLibraryAuthors(LibraryInput):
    operation: Literal["list_library_authors"] = op("list_library_authors", "List Library Author Metadata")


class GetAuthor(LibraryInput):
    operation: Literal["get_author"] = op("get_author", "Get Author Metadata")
    author_id: ID = Field(..., title="Author", description="Exact UUID witnessed in the selected library's current author catalog. Author responses do not contain a library parent ID.", json_schema_extra={"x-resource-type": "audiobookshelf_author", "x-dynamic-options": {"field_name": "author_id", "searchable": True, "allow_custom": True, "depends_on": "library_id"}})

    @field_validator("author_id", mode="before")
    @classmethod
    def exact_author(cls, value): return identifier(value)


Config = Annotated[Union[ListLibraries, GetLibrary, ListLibraryAuthors, GetAuthor], Field(discriminator="operation")]


class AudiobookshelfNodeConfig(NodeConfig[Config, AudiobookshelfAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class PrivateHeaders(dict):
    def __repr__(self): return "<private Audiobookshelf API-key headers>"
    __str__ = __repr__


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("Repeated Audiobookshelf metadata field")
        result[key] = value
    return result


def invalid_number(_value): raise ValueError("Nonfinite Audiobookshelf number")


async def request(value, resource, *, library_id=None, author_id=None, reader=None):
    if resource == "libraries" and library_id is None and author_id is None: endpoint = "/libraries"
    elif resource == "library" and author_id is None: endpoint = "/libraries/" + quote(identifier(library_id), safe="")
    elif resource == "authors" and author_id is None: endpoint = "/libraries/" + quote(identifier(library_id), safe="") + "/authors"
    elif resource == "author" and library_id is None: endpoint = "/authors/" + quote(identifier(author_id), safe="")
    else: raise ValueError("Unsupported Audiobookshelf metadata operation")
    if reader: value = await reader.read()
    headers = PrivateHeaders({"Authorization": "Bearer " + value.api_key, "Accept": "application/json", "Cache-Control": "no-store"})
    status = None
    try:
        try:
            if allow_private_hosts():
                raise ValueError("Audiobookshelf requires public-host enforcement")
            async with guarded_async_client(timeout=12, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", value.instance_origin + "/api" + endpoint, headers=headers) as response:
                    status = response.status_code
                    if status != 200 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError("Audiobookshelf metadata status/format unavailable")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES: raise ValueError("Audiobookshelf metadata exceeds local 2MiB bound")
            payload = json.loads(raw, object_pairs_hook=unique_json, parse_constant=invalid_number)
            if not isinstance(payload, dict): raise ValueError("Audiobookshelf metadata requires an object")
            return payload
        except Exception:
            suffix = f" (HTTP {status})" if type(status) is int and 100 <= status <= 599 else ""
            raise ValueError("Audiobookshelf metadata could not be established" + suffix + "; key/instance/version/permissions/service cause unknown") from None
    finally:
        if reader: await reader.read()


def record(row, kind, *, names=False, expanded=False):
    if not isinstance(row, dict): raise ValueError("Audiobookshelf metadata requires a typed object")
    result = {"id": identifier(row.get("id"))}
    if kind == "library":
        integer_fields = ("displayOrder", "createdAt", "lastUpdate")
        if "mediaType" in row: result["mediaType"] = scalar_text(row["mediaType"])
    elif kind == "author": integer_fields = ("addedAt", "updatedAt")
    else: raise ValueError("Unsupported Audiobookshelf resource kind")
    for key in integer_fields:
        if key in row:
            if type(row[key]) is not int: raise ValueError("Audiobookshelf integer metadata witness is malformed")
            result[key] = row[key]
    if names and "name" in row: result["name"] = scalar_text(row["name"])
    if kind == "author" and expanded and "numBooks" in row:
        if type(row["numBooks"]) is not int: raise ValueError("Audiobookshelf author catalog book count requires an integer")
        result["resource_linked_book_count"] = row["numBooks"]
    return result


def catalog(payload, kind):
    key = {"library": "libraries", "author": "authors"}.get(kind)
    if not isinstance(payload, dict) or key is None or not isinstance(payload.get(key), list):
        raise ValueError("Audiobookshelf requires the documented resource array")
    rows = payload[key]
    ids = [record(r, kind, expanded=kind == "author")["id"] for r in rows]
    if len(ids) != len(set(ids)): raise ValueError("Audiobookshelf catalog repeated a resource ID")
    return rows


def result_page(payload, kind, *, names=False):
    rows = catalog(payload, kind)
    return {"items": [record(r, kind, names=names, expanded=kind == "author") for r in rows[:MAX_OUTPUT]], "count": min(len(rows), MAX_OUTPUT), "total": None, "has_more": None, "completion_verified": False, "truncated": len(rows) > MAX_OUTPUT, "local_output_limit": MAX_OUTPUT, "snapshot_verified": False, "principal_identity_verified": False, "ownership_verified": False}


async def witness_library(value, selected, *, reader=None, names=False):
    before = catalog(await request(value, "libraries", reader=reader), "library")
    if len(before) > MAX_OUTPUT: raise ValueError("Audiobookshelf library witness exceeds local 100 catalog bound")
    if not any(r["id"] == selected for r in before): raise ValueError("Audiobookshelf selected library unavailable in the current catalog")
    detail = record(await request(value, "library", library_id=selected, reader=reader), "library", names=names)
    if detail["id"] != selected: raise ValueError("Audiobookshelf returned a different library ID")
    after = catalog(await request(value, "libraries", reader=reader), "library")
    if len(after) > MAX_OUTPUT: raise ValueError("Audiobookshelf library witness exceeds local 100 catalog bound")
    if not any(r["id"] == selected for r in after): raise ValueError("Audiobookshelf library access changed during this call")
    return detail


class AudiobookshelfNode(WorkflowNode):
    integration_type = "automation-audiobookshelf"
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_libraries", noun="key-visible libraries catalog metadata", proves="reachability")

    @classmethod
    def get_config_model(cls): return AudiobookshelfNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._freshen_for_execution(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def _freshen_for_execution(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=None):
        value = guard(credential_data)
        if not credential_id: return value.model_dump()
        if not user_id: raise ValueError("Stored Audiobookshelf credentials require a caller")
        reader = Reader(credential_id, user_id, organization_id, workflow_id, pool, expected=authority(value))
        fresh = await reader.read()
        return {**fresh.model_dump(), "_audiobookshelf_reader": reader}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        value = guard(credential_data); reader = credential_data.get("_audiobookshelf_reader")
        if reader is not None and not isinstance(reader, Reader): raise ValueError("Invalid Audiobookshelf current-row reader")
        try:
            if field_name not in {"library_id", "author_id"} or page_token is not None: raise ValueError("Audiobookshelf has two metadata pickers and no documented paging")
            search = "" if search is None else search
            if not isinstance(search, str) or len(search) > 256: raise ValueError("Supply a bounded local Audiobookshelf picker search")
            context = context or {}
            if field_name == "library_id":
                kind = "library"
                rows = catalog(await request(value, "libraries", reader=reader), kind)
            else:
                kind = "author"; selected = identifier(context.get("library_id"))
                await witness_library(value, selected, reader=reader)
                rows = catalog(await request(value, "authors", library_id=selected, reader=reader), kind)
                await witness_library(value, selected, reader=reader)
            if len(rows) > MAX_OUTPUT: raise ValueError("Audiobookshelf picker exceeds local 100 output bound; completeness remains unknown")
            names = context.get("include_names") is True
            options = []
            for row in rows:
                label = scalar_text(row["name"]) if names and "name" in row else f"{kind.title()} {row['id']}"
                if search.casefold() in (row["id"] + " " + label).casefold(): options.append({"value": row["id"], "label": label})
            return {"options": options, "next_page_token": None}
        finally:
            if reader: await reader.read()

    async def execute(self, inputs):
        cfg = self.config.config
        raw = self.node_data.get("credentials") or (self.config.credentials.model_dump() if self.config.credentials is not None else None)
        data = await self._freshen_for_execution(raw, credential_id=self.node_data.get("credential_id"), user_id=self.user_id, workflow_id=self.workflow_id, organization_id=self.organization_id, pool=self.node_data.get("_approval_pool"))
        value, reader = guard(data), data.get("_audiobookshelf_reader")
        try:
            if cfg.operation == "list_libraries": return result_page(await request(value, "libraries", reader=reader), "library", names=cfg.include_names)
            selected = identifier(cfg.library_id)
            detail = await witness_library(value, selected, reader=reader, names=cfg.include_names and cfg.operation == "get_library")
            if cfg.operation == "get_library": return detail
            payload = await request(value, "authors", library_id=selected, reader=reader)
            before = catalog(payload, "author")
            if cfg.operation == "list_library_authors":
                await witness_library(value, selected, reader=reader)
                return result_page(payload, "author", names=cfg.include_names)
            if cfg.operation != "get_author": raise ValueError("Unsupported Audiobookshelf metadata operation")
            author_id = identifier(cfg.author_id)
            if len(before) > MAX_OUTPUT: raise ValueError("Audiobookshelf author witness exceeds local 100 catalog bound")
            if not any(r["id"] == author_id for r in before): raise ValueError("Audiobookshelf selected author unavailable in the selected library catalog")
            author = record(await request(value, "author", author_id=author_id, reader=reader), "author", names=cfg.include_names)
            if author["id"] != author_id: raise ValueError("Audiobookshelf returned a different author ID")
            after = catalog(await request(value, "authors", library_id=selected, reader=reader), "author")
            if len(after) > MAX_OUTPUT: raise ValueError("Audiobookshelf author witness exceeds local 100 catalog bound")
            if not any(r["id"] == author_id for r in after): raise ValueError("Audiobookshelf author access changed during this call")
            await witness_library(value, selected, reader=reader)
            return author
        finally:
            if reader: await reader.read()
