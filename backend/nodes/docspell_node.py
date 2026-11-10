"""Three closed Docspell folder/tag metadata reads at one HTTPS origin.

Token-visible catalogs prove reachability/access, never principal or ownership.
Items, document content, users, membership and control routes are omitted.
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
from repositories.docspell_credentials import fetch_snapshot
from utils.ssrf import allow_private_hosts, guarded_async_client, normalize_https_origin

TYPE = "docspell_auth_token"
MAX_BYTES = 2 * 1024 * 1024
MAX_OUTPUT = 100
MAX_COUNT = 2147483647  # TagList.count documents int32; no created epoch unit assumed.
OPERATIONS = {"list_folders", "get_folder", "list_tags"}
ID = Annotated[StrictStr, Field(min_length=1, max_length=256)]


def identifier(value):
    # Local safety bounds only; vendor ident has no documented grammar.
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Docspell requires an exact locally bounded opaque string ID")
    return value


def scalar_text(value):
    if not isinstance(value, str) or len(value) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Docspell returned malformed scalar text")
    return value


class DocspellAuthTokenCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, title="Docspell Auth Token", json_schema_extra={"x-credential-url": "https://docspell.org/docs/api/intro/"})
    credential_type: Literal["docspell_auth_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    instance_origin: str = Field(..., repr=False, title="Instance HTTPS Origin", description="One public HTTPS origin, with no credentials/path/query/fragment. API paths are fixed /api/v1. Hosted/self-hosted instance version parity is unverified.")
    auth_token: str = Field(..., min_length=1, max_length=8192, repr=False, title="Existing User Token", description="Supplied existing authenticated-user token, X-Docspell-Auth header only. No login, admin/share token, JWT parsing or mint/refresh/extend.", json_schema_extra={"ui:widget": "password"})

    @model_serializer(mode="wrap")
    def canonical(self, handler):
        return {**handler(self), "credential_type": TYPE}

    @field_validator("instance_origin", mode="before")
    @classmethod
    def origin(cls, value):
        try:
            if not isinstance(value, str): raise ValueError()
            normalized = normalize_https_origin(value, field_name="Docspell instance")
            host = urlsplit(normalized).hostname
            if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")): raise ValueError()
            try: address = ipaddress.ip_address(host)
            except ValueError: address = None
            if address is not None and not address.is_global: raise ValueError()
            return normalized
        except ValueError:
            raise ValueError("Supply one public HTTPS Docspell origin without paths or credentials") from None

    @field_validator("auth_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply the existing Docspell user token without whitespace")
        return value


def guard(data):
    if not isinstance(data, dict) or data.get("credential_type") != TYPE:
        raise ValueError("Connect a typed Docspell user token")
    try:
        return DocspellAuthTokenCredential.model_validate({k: v for k, v in data.items() if k not in {"_docspell_reader", "token_version", "updated_at"}})
    except ValueError:
        raise ValueError("Docspell credential shape is invalid; reconnect it") from None


def authority(value):
    return value.credential_type, value.instance_origin, value.auth_token

async def current(credential_id, user_id, organization_id=None, workflow_id=None, *, pool=None):
    if not user_id:
        raise ValueError("Stored Docspell credentials require a caller")
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
        raise ValueError("Docspell credential is unavailable or has the wrong type/version")
    try:
        data = get_encryption().decrypt_credential(row["credential"])
    except Exception:
        raise ValueError("Docspell credential cannot be read") from None
    if not isinstance(data, dict) or data.get("credential_type") != row["credential_type"]:
        raise ValueError("Docspell saved credential type does not match its row")
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
            raise ValueError("Docspell cached credential changed; reload it")
        binding = (owner, version, *authority(value))
        if self.anchor is not None and binding != self.anchor:
            raise ValueError("Docspell saved credential changed during this call")
        self.anchor = binding
        return value


def op(value, title):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Metadata", "x-is-trigger": False})


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    include_names: StrictBool = Field(False, title="Include Names", description="Opt in to folder/tag names. Owners, members, permission metadata and tag categories are omitted.")


class ListFolders(Input):
    operation: Literal["list_folders"] = op("list_folders", "List Folder Metadata")


class GetFolder(Input):
    operation: Literal["get_folder"] = op("get_folder", "Get Folder Metadata")
    folder_id: ID = Field(..., title="Folder", description="Exact current token-visible opaque string ID; no vendor grammar or numeric conversion. Catalog/detail/catalog witnesses access, not ownership.", json_schema_extra={"x-resource-type": "docspell_folder", "x-dynamic-options": {"field_name": "folder_id", "searchable": True, "allow_custom": True}})

    @field_validator("folder_id", mode="before")
    @classmethod
    def opaque_id(cls, value):
        return identifier(value)


class ListTags(Input):
    operation: Literal["list_tags"] = op("list_tags", "List Tag Metadata")


Config = Annotated[Union[ListFolders, GetFolder, ListTags], Field(discriminator="operation")]


class DocspellNodeConfig(NodeConfig[Config, DocspellAuthTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class PrivateHeaders(dict):
    def __repr__(self): return "<private Docspell user-token headers>"
    __str__ = __repr__


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("Repeated Docspell metadata field")
        result[key] = value
    return result


def invalid_number(_value):
    raise ValueError("Nonfinite Docspell number")


async def request(value, resource, *, folder_id=None, reader=None):
    if resource == "folders" and folder_id is None: endpoint = "/sec/folder"
    elif resource == "tags" and folder_id is None: endpoint = "/sec/tag"
    elif resource == "folder": endpoint = "/sec/folder/" + quote(identifier(folder_id), safe="")
    else: raise ValueError("Unsupported Docspell metadata operation")
    if reader: value = await reader.read()
    headers = PrivateHeaders({"X-Docspell-Auth": value.auth_token, "Accept": "application/json", "Cache-Control": "no-store"})
    status = None
    try:
        try:
            if allow_private_hosts():
                raise ValueError("Docspell requires public-host enforcement")
            async with guarded_async_client(timeout=12, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", value.instance_origin + "/api/v1" + endpoint, headers=headers) as response:
                    status = response.status_code
                    if status != 200 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError("Docspell metadata status/format unavailable")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES: raise ValueError("Docspell metadata exceeds local2MiB bound")
            payload = json.loads(raw, object_pairs_hook=unique_json, parse_constant=invalid_number)
            if not isinstance(payload, dict): raise ValueError("Docspell metadata requires an object envelope")
            return payload
        except Exception:
            suffix = f" (HTTP {status})" if type(status) is int and 100 <= status <= 599 else ""
            raise ValueError("Docspell metadata could not be established" + suffix + "; token/instance/version/permissions/service cause unknown") from None
    finally:
        if reader: await reader.read()


def record(row, *, names=False):
    if not isinstance(row, dict): raise ValueError("Docspell metadata requires a typed object")
    created = row.get("created")
    if type(created) is not int: raise ValueError("Docspell requires the raw integer created witness; units unknown")
    result = {"id": identifier(row.get("id")), "created": created}
    if names: result["name"] = scalar_text(row.get("name"))
    return result


def catalog(payload, kind):
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list): raise ValueError("Docspell requires the items array catalog")
    if kind == "tag":
        count = payload.get("count")
        if type(count) is not int or not 0 <= count <= MAX_COUNT: raise ValueError("Docspell tag count requires a nonnegative int32 witness")
    elif kind != "folder": raise ValueError("Unsupported Docspell catalog kind")
    rows = payload["items"]
    ids = [record(r)["id"] for r in rows]
    if len(ids) != len(set(ids)): raise ValueError("Docspell catalog repeated a resource ID")
    return rows


def result_page(payload, kind, *, names=False):
    rows = catalog(payload, kind)
    count_witness = {"catalog_count": payload["count"]} if kind == "tag" else {}
    return {"items": [record(r, names=names) for r in rows[:MAX_OUTPUT]], "count": min(len(rows), MAX_OUTPUT), "total": None, "has_more": None, "completion_verified": False, "truncated": len(rows) > MAX_OUTPUT, "local_output_limit": MAX_OUTPUT, "snapshot_verified": False, "principal_identity_verified": False, "ownership_verified": False, **count_witness}


class DocspellNode(WorkflowNode):
    integration_type = "automation-docspell"
    credential_provider_labels = {"docspell": "Docspell Account"}
    auto_select_credential = False
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_folders", noun="token-visible folders catalog metadata", proves="reachability")

    @classmethod
    def get_config_model(cls): return DocspellNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        # Folder identifiers are opaque strings. The shared parser's numeric
        # string coercion would select a different ID than the caller supplied.
        return DocspellNodeConfig.model_validate(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._freshen_for_execution(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def _freshen_for_execution(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=None):
        value = guard(credential_data)
        if not credential_id: return value.model_dump()
        if not user_id: raise ValueError("Stored Docspell credentials require a caller")
        reader = Reader(credential_id, user_id, organization_id, workflow_id, pool, expected=authority(value))
        fresh = await reader.read()
        return {**fresh.model_dump(), "_docspell_reader": reader}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        value = guard(credential_data); reader = credential_data.get("_docspell_reader")
        if reader is not None and not isinstance(reader, Reader): raise ValueError("Invalid Docspell current-row reader")
        try:
            if field_name != "folder_id" or page_token is not None: raise ValueError("Docspell has one folder picker and no documented paging")
            search = "" if search is None else search
            if not isinstance(search, str) or len(search) > 256: raise ValueError("Supply a bounded local Docspell picker search")
            rows = catalog(await request(value, "folders", reader=reader), "folder")
            if len(rows) > MAX_OUTPUT: raise ValueError("Docspell picker exceeds local100 output bound; completeness remains unknown")
            names = (context or {}).get("include_names") is True
            options = []
            for row in rows:
                label = scalar_text(row.get("name")) if names else f"Folder {row['id']}"
                if search.casefold() in (row["id"] + " " + label).casefold(): options.append({"value": row["id"], "label": label})
            return {"options": options, "next_page_token": None}
        finally:
            if reader: await reader.read()

    async def execute(self, inputs):
        cfg = self.config.config
        raw = self.node_data.get("credentials") or (self.config.credentials.model_dump() if self.config.credentials is not None else None)
        data = await self._freshen_for_execution(raw, credential_id=self.node_data.get("credential_id"), user_id=self.user_id, workflow_id=self.workflow_id, organization_id=self.organization_id, pool=self.node_data.get("_approval_pool"))
        value, reader = guard(data), data.get("_docspell_reader")
        try:
            if cfg.operation == "list_folders": return result_page(await request(value, "folders", reader=reader), "folder", names=cfg.include_names)
            if cfg.operation == "list_tags": return result_page(await request(value, "tags", reader=reader), "tag", names=cfg.include_names)
            if cfg.operation != "get_folder": raise ValueError("Unsupported Docspell metadata operation")
            selected = identifier(cfg.folder_id)
            before = catalog(await request(value, "folders", reader=reader), "folder")
            if not any(r["id"] == selected for r in before): raise ValueError("Docspell selected folder unavailable in the current catalog")
            detail = record(await request(value, "folder", folder_id=selected, reader=reader), names=cfg.include_names)
            if detail["id"] != selected: raise ValueError("Docspell returned a different folder ID")
            after = catalog(await request(value, "folders", reader=reader), "folder")
            if not any(r["id"] == selected for r in after): raise ValueError("Docspell folder access changed during this call")
            return detail
        finally:
            if reader: await reader.read()
