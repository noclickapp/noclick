"""Closed Bytescale secret-key metadata reads under explicit account/folder scope.

Protected catalog visibility establishes reachability, never a human principal
or account ownership. Returned capabilities, settings and custom data are omitted.
"""
import base64
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Annotated, Any, Literal, Union

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_serializer
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from repositories.bytescale_credentials import fetch_snapshot
from utils.ssrf import guarded_async_client

ROOT = "https://api.bytescale.com/v2"
TYPE = "bytescale_secret_api_key"
MAX_BYTES = 2 * 1024 * 1024
PAGE_LIMIT = 100
MAX_PAGES = 10
MAX_DEPTH = 4
OPERATIONS = {"list_folder", "get_folder_details", "get_file_details"}


def path(value, *, file=False):
    if not isinstance(value, str) or not 1 <= len(value) <= 512 or not value.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in value) or any(c in value for c in "\\%*"):
        raise ValueError("Supply a canonical absolute Bytescale path, at most 512 characters")
    if value != "/" and (value.endswith("/") or any(s in {"", ".", ".."} for s in value[1:].split("/"))):
        raise ValueError("Bytescale paths must not contain empty or dot segments")
    if file and value == "/":
        raise ValueError("Select a file below the selected folder")
    return value


def text(value, *, maximum=512):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Bytescale returned malformed metadata text")
    return value


def within(child, parent):
    return child == parent or child.startswith(parent.rstrip("/") + "/")


def parent_of(value):
    return value.rsplit("/", 1)[0] or "/"


class BytescaleSecretAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, title="Bytescale Secret API Key", json_schema_extra={"x-credential-type": TYPE, "x-credential-url": "https://www.bytescale.com/docs/auth/api-keys"})
    credential_type: Literal["bytescale_secret_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=8, max_length=8192, repr=False, title="Secret API Key", description="Supplied secret_* management key. Public upload/download keys and JWTs are separate auth families. Sent only as Bearer Authorization to api.bytescale.com; no exchange or renewal.", json_schema_extra={"ui:widget": "password"})
    account_id: str = Field(..., pattern=r"^[A-Za-z0-9]{7}$", title="Account ID", description="Exact seven-character account ID from Bytescale settings. Resource visibility does not prove ownership.")
    folder_paths: list[str] = Field(..., min_length=1, max_length=20, title="Allowed Folder Paths", description="Explicit absolute folder roots this node may read. Descendants require current catalog/parent witnesses. Local subset excludes percent/backslash/dot/empty segments; no wildcard paths.")

    @model_serializer(mode="wrap")
    def canonical(self, handler):
        return {**handler(self), "credential_type": TYPE}

    @field_validator("api_key", mode="before")
    @classmethod
    def secret_key(cls, value):
        if not isinstance(value, str) or not value.startswith("secret_") or not 8 <= len(value) <= 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply the secret_* management API key without an authorization prefix")
        return value

    @field_validator("folder_paths")
    @classmethod
    def roots(cls, value):
        result = [path(p) for p in value]
        if len(result) != len(set(result)):
            raise ValueError("Supply unique allowed folder roots")
        return result


def guard(data):
    if not isinstance(data, dict) or data.get("credential_type") != TYPE:
        raise ValueError("Connect a typed Bytescale secret API key credential")
    try:
        return BytescaleSecretAPIKeyCredential.model_validate({k: v for k, v in data.items() if k not in {"_bytescale_reader", "token_version", "updated_at"}})
    except ValueError:
        raise ValueError("Bytescale credential shape is invalid; reconnect it") from None


def authority(value):
    return value.credential_type, value.account_id, tuple(value.folder_paths), value.api_key


async def current(credential_id, user_id, organization_id=None, workflow_id=None, *, pool=None):
    if not user_id:
        raise ValueError("Stored Bytescale credentials require a caller")
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
        raise ValueError("Bytescale credential is unavailable or has the wrong type/version")
    try:
        data = get_encryption().decrypt_credential(row["credential"])
    except Exception:
        raise ValueError("Bytescale credential cannot be read") from None
    if not isinstance(data, dict) or data.get("credential_type") != row["credential_type"]:
        raise ValueError("Bytescale saved credential type does not match its row")
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
            raise ValueError("Bytescale cached credential changed; reload it")
        binding = (owner, version, *authority(value))
        if self.anchor is not None and binding != self.anchor:
            raise ValueError("Bytescale saved credential changed during this call")
        self.anchor = binding
        return value


def op(value, title):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Metadata", "x-is-trigger": False})


def resource(name):
    return {"x-resource-type": "bytescale_" + name.removesuffix("_path"), "x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True, **({"depends_on": ["folder_path"]} if name == "file_path" else {})}}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    folder_path: str | None = Field(None, max_length=512, title="Folder", description="An allowed root or a currently cataloged descendant, at most four levels below a saved root. If omitted, use the first allowed root. File pickers require an explicitly selected parent.", json_schema_extra=resource("folder_path"))
    include_paths_and_names: StrictBool = Field(False, title="Include Names and Paths", description="Opt in to returned paths/original file names, which can contain private data. Types, sizes and MIME/virtual flags are returned by default.")

    @field_validator("folder_path")
    @classmethod
    def folder(cls, value):
        return None if value is None else path(value)


class ListFolder(Input):
    operation: Literal["list_folder"] = op("list_folder", "List Folder Metadata")
    limit: Annotated[StrictInt, Field(ge=1, le=100)] = Field(20, title="Page Size", description="Documented maximum1000, locally capped at100. At most ten pages per encrypted continuation; no snapshot or total is inferred.")
    page_token: str | None = Field(None, max_length=131072, title="Continuation", description="Only the encrypted continuation returned by this native operation. Bound to the supplied key/account/roots, parent and page size; not a raw provider cursor.")


class GetFolderDetails(Input):
    operation: Literal["get_folder_details"] = op("get_folder_details", "Get Folder Metadata")


class GetFileDetails(Input):
    operation: Literal["get_file_details"] = op("get_file_details", "Get File Metadata")
    file_path: str = Field(..., min_length=1, max_length=512, title="File", description="Exact file path directly inside the selected folder; current list membership is required before details.", json_schema_extra=resource("file_path"))

    @field_validator("file_path")
    @classmethod
    def file(cls, value):
        return path(value, file=True)


Config = Annotated[Union[ListFolder, GetFolderDetails, GetFileDetails], Field(discriminator="operation")]


class BytescaleNodeConfig(NodeConfig[Config, BytescaleSecretAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class PrivateHeaders(dict):
    def __repr__(self):
        return "<private Bytescale authorization header>"
    __str__ = __repr__


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated Bytescale metadata field")
        result[key] = value
    return result


def invalid_number(_value):
    raise ValueError("Nonfinite Bytescale metadata number")


async def request(value, endpoint, *, query, reader=None):
    required = {"folders/list": {"folderPath", "limit"}, "folders": {"folderPath"}, "files/details": {"filePath"}}
    if endpoint not in required or not required[endpoint] <= set(query) or set(query) - required[endpoint] != ({"cursor"} if endpoint == "folders/list" and "cursor" in query else set()):
        raise ValueError("Unsupported Bytescale metadata route or query")
    selected = path(query.get("folderPath", query.get("filePath")), file=endpoint == "files/details")
    if not any(within(selected, root) for root in value.folder_paths):
        raise ValueError("Bytescale path is outside the saved folder scope")
    if endpoint == "folders/list":
        if type(query["limit"]) is not int or not 1 <= query["limit"] <= PAGE_LIMIT:
            raise ValueError("Supply a bounded Bytescale page size")
        if "cursor" in query:
            text(query["cursor"])
    if reader:
        value = await reader.read()
    try:
        try:
            async with guarded_async_client(timeout=12, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", f"{ROOT}/accounts/{value.account_id}/{endpoint}", params=query, headers=PrivateHeaders({"Authorization": "Bearer " + value.api_key, "Accept": "application/json", "Cache-Control": "no-store"})) as response:
                    if response.status_code != 200 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError("Bytescale metadata read refused or format unavailable")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES:
                            raise ValueError("Bytescale metadata exceeds the local2MiB bound")
            return json.loads(raw, object_pairs_hook=unique_json, parse_constant=invalid_number)
        except Exception:
            raise ValueError("Bytescale metadata read could not be established; inspect key, account, permissions, entitlement or service availability") from None
    finally:
        if reader:
            await reader.read()


def summary(row, *, include_paths=False):
    if not isinstance(row, dict) or row.get("type") not in {"File", "Folder"}:
        raise ValueError("Malformed Bytescale item kind")
    result = {"type": row["type"]}
    if row["type"] == "File":
        selected = path(row.get("filePath"), file=True)
        if type(row.get("size")) is not int or row["size"] < 0:
            raise ValueError("Malformed Bytescale file size")
        result["size"] = row["size"]
    else:
        selected = path(row.get("folderPath"))
        if type(row.get("virtual")) is not bool:
            raise ValueError("Malformed Bytescale folder flag")
        result["virtual"] = row["virtual"]
    if include_paths:
        result["path"] = selected
    return result, selected


def page(payload, selected, limit):
    if not isinstance(payload, dict) or type(payload.get("isPaginationComplete")) is not bool or not isinstance(payload.get("items"), list) or len(payload["items"]) > limit:
        raise ValueError("Bytescale requires the documented bounded folder/items/pagination envelope")
    folder, folder_path = summary(payload.get("folder"))
    if folder["type"] != "Folder" or folder_path != selected:
        raise ValueError("Bytescale returned a different selected folder")
    paths = []
    for row in payload["items"]:
        _, item_path = summary(row)
        if parent_of(item_path) != selected or item_path == selected:
            raise ValueError("Bytescale returned an item outside its selected parent")
        paths.append(item_path)
    if len(paths) != len(set(paths)):
        raise ValueError("Bytescale returned repeated resource paths")
    cursor = text(payload.get("cursor"))
    return payload["items"], cursor, payload["isPaginationComplete"], folder


def cipher(value):
    key = hashlib.sha256(json.dumps(authority(value), separators=(",", ":")).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def continuation(value, token, binding):
    if token is None:
        return None, [], 0
    try:
        if not isinstance(token, str) or not 1 <= len(token) <= 131072:
            raise ValueError()
        obj = json.loads(cipher(value).decrypt(token.encode()), object_pairs_hook=unique_json)
        if not isinstance(obj, dict) or set(obj) != {"binding", "cursor", "seen", "pages"} or obj["binding"] != binding or type(obj["pages"]) is not int or not 1 <= obj["pages"] < MAX_PAGES or not isinstance(obj["seen"], list) or len(obj["seen"]) > PAGE_LIMIT * MAX_PAGES or any(not isinstance(s, str) or not re.fullmatch(r"[a-f0-9]{64}", s) for s in obj["seen"]) or len(obj["seen"]) != len(set(obj["seen"])):
            raise ValueError()
        return text(obj["cursor"]), obj["seen"], obj["pages"]
    except (ValueError, TypeError, UnicodeError, InvalidToken):
        raise ValueError("Bytescale continuation is invalid or its credential/parent/filter changed") from None


def next_token(value, binding, cursor, seen, pages):
    raw = json.dumps({"binding": binding, "cursor": cursor, "seen": seen, "pages": pages}, separators=(",", ":"), sort_keys=True).encode()
    result = cipher(value).encrypt(raw).decode()
    if len(result) > 131072:
        raise ValueError("Bytescale continuation exceeds the local bound")
    return result


def reader_from(data):
    reader = data.get("_bytescale_reader")
    if reader is not None and not isinstance(reader, Reader):
        raise ValueError("Invalid Bytescale current-row reader")
    return reader


class BytescaleNode(WorkflowNode):
    integration_type = "automation-bytescale"
    credential_provider_labels = {"bytescale": "Bytescale Account"}
    auto_select_credential = False
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_folder", noun="accessible folder metadata", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return BytescaleNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._freshen_for_context(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def _freshen_for_context(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=None):
        value = guard(credential_data)
        if not credential_id:
            return value.model_dump()
        if not user_id:
            raise ValueError("Stored Bytescale credentials require a caller")
        reader = Reader(credential_id, user_id, organization_id, workflow_id, pool, expected=authority(value))
        current_value = await reader.read()
        return {**current_value.model_dump(), "_bytescale_reader": reader}

    @classmethod
    async def _page(cls, value, folder, reader, *, limit=PAGE_LIMIT, cursor=None):
        query = {"folderPath": folder, "limit": limit}
        if cursor is not None:
            query["cursor"] = cursor
        return page(await request(value, "folders/list", query=query, reader=reader), folder, limit)

    @classmethod
    async def _member(cls, value, folder, selected, kind, reader):
        cursor, seen_cursors, seen_items = None, set(), set()
        for _ in range(MAX_PAGES):
            items, successor, complete, _summary = await cls._page(value, folder, reader, cursor=cursor)
            for row in items:
                _, item_path = summary(row)
                if item_path in seen_items:
                    raise ValueError("Bytescale membership catalog repeated a resource")
                seen_items.add(item_path)
            if any(row["type"] == kind and row.get("filePath", row.get("folderPath")) == selected for row in items):
                return
            if complete:
                raise ValueError("Selected Bytescale resource is absent from its current parent catalog")
            if successor in seen_cursors:
                raise ValueError("Bytescale membership cursor did not progress")
            seen_cursors.add(successor)
            cursor = successor
        raise ValueError("Bytescale membership exceeds the local ten-page bound")

    @classmethod
    async def _folder(cls, value, selected, reader):
        selected = path(selected)
        roots = [root for root in value.folder_paths if within(selected, root)]
        if not roots:
            raise ValueError("Bytescale folder is outside the saved scope")
        root = max(roots, key=len)
        suffix = selected[len(root.rstrip("/")):].strip("/")
        parts = suffix.split("/") if suffix else []
        if len(parts) > MAX_DEPTH:
            raise ValueError("Bytescale folder ancestry exceeds the local four-level bound")
        # The selected saved root itself needs a protected catalog witness.
        await cls._page(value, root, reader, limit=1)
        parent = root
        for part in parts:
            child = parent.rstrip("/") + "/" + part
            await cls._member(value, parent, child, "Folder", reader)
            parent = child
        return selected

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search_query=None, page_token=None, *, search=None):
        value, reader = guard(credential_data), reader_from(credential_data)
        context = context or {}
        search = search if search is not None else search_query
        if search is None:
            search = ""
        if not isinstance(search, str) or len(search) > 256:
            raise ValueError("Supply a bounded Bytescale picker search")
        try:
            if field_name == "folder_path":
                if page_token:
                    raise ValueError("Allowed Bytescale folder roots have no picker continuation")
                options = []
                for index, folder in enumerate(value.folder_paths):
                    await cls._page(value, folder, reader, limit=1)
                    if search.casefold() in folder.casefold():
                        options.append({"value": folder, "label": folder if context.get("include_paths_and_names") is True else f"Allowed folder {index + 1}"})
                return {"options": options, "next_page_token": None}
            if field_name != "file_path" or not context.get("folder_path"):
                raise ValueError("Select a Bytescale parent folder before loading files")
            folder = path(context["folder_path"])
            binding = {"mode": "file_picker", "folder": folder, "limit": 50, "search": search, "include_paths": context.get("include_paths_and_names") is True}
            cursor, seen, pages = continuation(value, page_token, binding)
            await cls._folder(value, folder, reader)
            items, successor, complete, _ = await cls._page(value, folder, reader, limit=50, cursor=cursor)
            hashes = [hashlib.sha256(summary(row)[1].encode()).hexdigest() for row in items]
            if set(hashes) & set(seen) or (cursor is not None and not complete and successor == cursor):
                raise ValueError("Bytescale picker page repeated an item or cursor")
            options = [{"value": row["filePath"], "label": row["filePath"] if binding["include_paths"] else f"File {len(seen) + i + 1}"} for i, row in enumerate(items) if row["type"] == "File" and search.casefold() in row["filePath"].casefold()]
            if not complete and pages + 1 >= MAX_PAGES:
                raise ValueError("Bytescale picker exceeds the local ten-page bound")
            return {"options": options, "next_page_token": None if complete else next_token(value, binding, successor, seen + hashes, pages + 1)}
        finally:
            if reader:
                await reader.read()

    async def execute(self, inputs):
        cfg = self.config.config
        raw = self.node_data.get("credentials") or (self.config.credentials.model_dump() if self.config.credentials is not None else None)
        data = await self._freshen_for_context(raw, credential_id=self.node_data.get("credential_id"), user_id=self.user_id, workflow_id=self.workflow_id, organization_id=self.organization_id, pool=self.node_data.get("_approval_pool"))
        value, reader = guard(data), reader_from(data)
        folder = cfg.folder_path or value.folder_paths[0]
        try:
            if cfg.operation == "get_file_details" and parent_of(cfg.file_path) != folder:
                raise ValueError("Bytescale file must be directly inside the selected folder")
            binding = {"mode": "list_folder", "folder": folder, "limit": cfg.limit, "include_paths": cfg.include_paths_and_names} if cfg.operation == "list_folder" else None
            cursor, seen, pages = continuation(value, cfg.page_token, binding) if cfg.operation == "list_folder" else (None, [], 0)
            await self._folder(value, folder, reader)
            if cfg.operation == "list_folder":
                rows, successor, complete, folder_metadata = await self._page(value, folder, reader, limit=cfg.limit, cursor=cursor)
                hashes = [hashlib.sha256(summary(row)[1].encode()).hexdigest() for row in rows]
                if set(hashes) & set(seen) or (cursor is not None and not complete and successor == cursor):
                    raise ValueError("Bytescale metadata page repeated an item or cursor")
                capped = not complete and pages + 1 >= MAX_PAGES
                result = {"items": [summary(row, include_paths=cfg.include_paths_and_names)[0] for row in rows], "count": len(rows), "folder": folder_metadata, "is_pagination_complete": complete, "local_limit_reached": capped, "next_page_token": None if complete or capped else next_token(value, binding, successor, seen + hashes, pages + 1), "total": None, "snapshot_verified": False, "principal_identity_verified": False, "account_ownership_verified": False}
                if cfg.include_paths_and_names:
                    result["folder_path"] = folder
                return result
            if cfg.operation == "get_folder_details":
                row = await request(value, "folders", query={"folderPath": folder}, reader=reader)
                if row == {}:
                    result = {"type": "Folder", "settings_configured": False, "metadata_available": False}
                    if cfg.include_paths_and_names:
                        result["path"] = folder
                    return result
                result, returned = summary(row, include_paths=cfg.include_paths_and_names)
                if returned != folder or result["type"] != "Folder":
                    raise ValueError("Bytescale returned a different selected folder")
                return result
            if cfg.operation != "get_file_details":
                raise ValueError("Unsupported Bytescale metadata operation")
            await self._member(value, folder, cfg.file_path, "File", reader)
            row = await request(value, "files/details", query={"filePath": cfg.file_path}, reader=reader)
            if not isinstance(row, dict) or row.get("accountId") != value.account_id or path(row.get("filePath"), file=True) != cfg.file_path:
                raise ValueError("Bytescale returned a different account or selected file")
            result, _ = summary({**row, "type": "File"}, include_paths=cfg.include_paths_and_names)
            result["mime"] = text(row.get("mime"), maximum=255)
            if len(result["mime"]) < 3:
                raise ValueError("Bytescale returned malformed MIME metadata")
            if cfg.include_paths_and_names and "originalFileName" in row:
                result["original_file_name"] = None if row["originalFileName"] is None else text(row["originalFileName"], maximum=255)
            return result
        finally:
            if reader:
                await reader.read()
