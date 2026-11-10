"""Three closed Linkwarden collection/tag metadata reads at one HTTPS origin.

Token-visible catalogs prove reachability/access, never principal or ownership.
Links, destinations, archive content, user fields and control routes are omitted.
"""
from dataclasses import dataclass, field
import ipaddress
import json
import math
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_serializer
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from repositories.linkwarden_credentials import fetch_snapshot
from utils.ssrf import allow_private_hosts, guarded_async_client, normalize_https_origin

TYPE = "linkwarden_access_token"
MAX_BYTES = 2 * 1024 * 1024
MAX_OUTPUT = 100
MAX_ID = 9007199254740991  # Local JavaScript-safe integer bound, not provider format.
OPERATIONS = {"list_collections", "get_collection", "list_tags"}
ID = Annotated[StrictInt, Field(gt=0, le=MAX_ID)]


def identifier(value):
    if type(value) is not int or not 0 < value <= MAX_ID:
        raise ValueError("Linkwarden requires a positive locally bounded integer ID")
    return value


def scalar_text(value):
    if not isinstance(value, str) or len(value) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Linkwarden returned malformed scalar text")
    return value


class LinkwardenAccessTokenCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, title="Linkwarden Access Token", json_schema_extra={"x-credential-type": TYPE, "x-credential-url": "https://docs.linkwarden.app/usage/profile-settings"})
    credential_type: Literal["linkwarden_access_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    instance_origin: str = Field(..., repr=False, title="Instance HTTPS Origin", description="One public HTTPS origin, with no credentials/path/query/fragment. API paths are fixed /api/v1. Hosted/self-hosted instance version parity is unverified.")
    access_token: str = Field(..., min_length=1, max_length=8192, repr=False, title="Existing Access Token", description="Supplied existing access token, Authorization Bearer header only. No login, JWT parsing, token mint/refresh or alternate auth.", json_schema_extra={"ui:widget": "password"})

    @model_serializer(mode="wrap")
    def canonical(self, handler):
        return {**handler(self), "credential_type": TYPE}

    @field_validator("instance_origin", mode="before")
    @classmethod
    def origin(cls, value):
        try:
            if not isinstance(value, str): raise ValueError()
            normalized = normalize_https_origin(value, field_name="Linkwarden instance")
            host = urlsplit(normalized).hostname
            if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")): raise ValueError()
            try: address = ipaddress.ip_address(host)
            except ValueError: address = None
            if address is not None and not address.is_global: raise ValueError()
            return normalized
        except ValueError:
            raise ValueError("Supply one public HTTPS Linkwarden origin without paths or credentials") from None

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply the existing Linkwarden access token without whitespace")
        return value


def guard(data):
    if not isinstance(data, dict) or data.get("credential_type") != TYPE:
        raise ValueError("Connect a typed Linkwarden access token")
    try:
        return LinkwardenAccessTokenCredential.model_validate({k: v for k, v in data.items() if k not in {"_linkwarden_reader", "token_version", "updated_at"}})
    except ValueError:
        raise ValueError("Linkwarden credential shape is invalid; reconnect it") from None


def authority(value):
    return value.credential_type, value.instance_origin, value.access_token

async def current(credential_id, user_id, organization_id=None, workflow_id=None, *, pool=None):
    if not user_id:
        raise ValueError("Stored Linkwarden credentials require a caller")
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
        raise ValueError("Linkwarden credential is unavailable or has the wrong type/version")
    try:
        data = get_encryption().decrypt_credential(row["credential"])
    except Exception:
        raise ValueError("Linkwarden credential cannot be read") from None
    if not isinstance(data, dict) or data.get("credential_type") != row["credential_type"]:
        raise ValueError("Linkwarden saved credential type does not match its row")
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
            raise ValueError("Linkwarden cached credential changed; reload it")
        binding = (owner, version, *authority(value))
        if self.anchor is not None and binding != self.anchor:
            raise ValueError("Linkwarden saved credential changed during this call")
        self.anchor = binding
        return value


def op(value, title):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Metadata", "x-is-trigger": False})


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    include_names: StrictBool = Field(False, title="Include Names", description="Opt in to collection/tag names. Owners, members, permissions, URLs, link content and parent metadata remain omitted.")


class ListCollections(Input):
    operation: Literal["list_collections"] = op("list_collections", "List Collection Metadata")


class GetCollection(Input):
    operation: Literal["get_collection"] = op("get_collection", "Get Collection Metadata")
    collection_id: ID = Field(..., title="Collection", description="Positive current token-visible collection ID. Current catalog/detail/catalog witnesses must match; access is not ownership.", json_schema_extra={"x-resource-type": "linkwarden_collection", "x-dynamic-options": {"field_name": "collection_id", "searchable": True, "allow_custom": True}})

    @field_validator("collection_id", mode="before")
    @classmethod
    def picker_id(cls, value):
        if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,15}", value): value = int(value)
        return identifier(value)


class ListTags(Input):
    operation: Literal["list_tags"] = op("list_tags", "List Tag Metadata")


Config = Annotated[Union[ListCollections, GetCollection, ListTags], Field(discriminator="operation")]


class LinkwardenNodeConfig(NodeConfig[Config, LinkwardenAccessTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class PrivateHeaders(dict):
    def __repr__(self): return "<private Linkwarden Bearer headers>"
    __str__ = __repr__


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("Repeated Linkwarden metadata field")
        result[key] = value
    return result


def invalid_number(_value):
    raise ValueError("Nonfinite Linkwarden number")


async def request(value, endpoint, *, reader=None):
    if endpoint not in {"/collections", "/tags"}:
        if re.fullmatch(r"/collections/[1-9][0-9]{0,15}", endpoint) is None:
            raise ValueError("Unsupported Linkwarden metadata route")
        identifier(int(endpoint.rsplit("/", 1)[1]))
    if reader: value = await reader.read()
    headers = PrivateHeaders({"Authorization": "Bearer " + value.access_token, "Accept": "application/json", "Cache-Control": "no-store"})
    try:
        try:
            # Staging's pinned transport guards public DNS/IPs unless explicitly
            # disabled for a trusted install. This node requires the guard.
            if allow_private_hosts():
                raise ValueError("Linkwarden requires public-only outbound transport")
            async with guarded_async_client(timeout=12, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", value.instance_origin + "/api/v1" + endpoint, headers=headers) as response:
                    if response.status_code != 200 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError("Linkwarden metadata read refused or format unavailable")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES: raise ValueError("Linkwarden metadata exceeds local2MiB bound")
            payload = json.loads(raw, object_pairs_hook=unique_json, parse_constant=invalid_number)
            if not isinstance(payload, dict): raise ValueError("Linkwarden metadata requires an object envelope")
            return payload
        except Exception:
            raise ValueError("Linkwarden metadata read could not be established; inspect token, instance/version, permissions or service availability") from None
    finally:
        if reader: await reader.read()


def record(row, kind, *, names=False):
    if not isinstance(row, dict): raise ValueError("Linkwarden metadata requires a typed object")
    result = {"id": identifier(row.get("id"))}
    for key in ("createdAt", "updatedAt"):
        if key in row: result[key] = scalar_text(row[key])
    if names and "name" in row: result["name"] = scalar_text(row["name"])
    if kind == "collection" and "isPublic" in row:
        if type(row["isPublic"]) is not bool: raise ValueError("Malformed Linkwarden public-state metadata")
        result["isPublic"] = row["isPublic"]
    if "_count" in row:
        if not isinstance(row["_count"], dict): raise ValueError("Malformed Linkwarden linked-resource count envelope")
        if "links" in row["_count"]:
            count = row["_count"]["links"]
            if type(count) is not int or count < 0: raise ValueError("Malformed Linkwarden linked-resource count")
            result["linked_resource_count"] = count
    return result


def catalog(payload, kind):
    if kind == "collection": rows = payload.get("response")
    else:
        if "success" in payload and type(payload["success"]) is not bool: raise ValueError("Malformed Linkwarden tag success witness")
        if payload.get("success") is False: raise ValueError("Linkwarden tag catalog was refused")
        data = payload.get("data")
        if not isinstance(data, dict): raise ValueError("Linkwarden requires the distinct tag data envelope")
        rows = data.get("tags")
        if "nextCursor" in data and data["nextCursor"] is not None:
            cursor = data["nextCursor"]
            if type(cursor) not in (int, float) or (type(cursor) is float and not math.isfinite(cursor)): raise ValueError("Malformed Linkwarden numeric tag cursor")
    if not isinstance(rows, list): raise ValueError("Linkwarden metadata catalog requires an array")
    ids = [record(r, kind)["id"] for r in rows]
    if len(ids) != len(set(ids)): raise ValueError("Linkwarden metadata repeated a resource ID")
    return rows


def result_page(payload, kind, *, names=False):
    rows = catalog(payload, kind); truncated = len(rows) > MAX_OUTPUT
    cursor_witness = {"next_cursor_witness_returned": payload["data"].get("nextCursor") is not None} if kind == "tag" else {}
    return {"items": [record(r, kind, names=names) for r in rows[:MAX_OUTPUT]], "count": min(len(rows), MAX_OUTPUT), "total": None, "has_more": None, "completion_verified": False, "truncated": truncated, "local_output_limit": MAX_OUTPUT, "snapshot_verified": False, "principal_identity_verified": False, "ownership_verified": False, **cursor_witness}


async def freshen_linkwarden_credential(credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=None):
    value = guard(credential_data)
    if not credential_id: return value.model_dump()
    if not user_id: raise ValueError("Stored Linkwarden credentials require a caller")
    reader = Reader(credential_id, user_id, organization_id, workflow_id, pool, expected=authority(value))
    fresh = await reader.read()
    return {**fresh.model_dump(), "_linkwarden_reader": reader}


class LinkwardenNode(WorkflowNode):
    integration_type = "automation-linkwarden"
    credential_provider_labels = {"linkwarden": "Linkwarden Account"}
    auto_select_credential = False
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_collections", noun="token-visible collections catalog metadata", proves="reachability")

    @classmethod
    def get_config_model(cls): return LinkwardenNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await freshen_linkwarden_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        value = guard(credential_data); reader = credential_data.get("_linkwarden_reader")
        if reader is not None and not isinstance(reader, Reader): raise ValueError("Invalid Linkwarden current-row reader")
        try:
            if field_name != "collection_id" or page_token is not None: raise ValueError("Linkwarden has one collection picker and no documented collection paging")
            search = "" if search is None else search
            if not isinstance(search, str) or len(search) > 256: raise ValueError("Supply a bounded local Linkwarden picker search")
            rows = catalog(await request(value, "/collections", reader=reader), "collection")
            if len(rows) > MAX_OUTPUT: raise ValueError("Linkwarden picker exceeds local100 output bound; no complete paging witness")
            names = (context or {}).get("include_names") is True
            options = []
            for row in rows:
                label = scalar_text(row["name"]) if names and "name" in row else f"Collection {row['id']}"
                if search.casefold() in (str(row["id"]) + " " + label).casefold(): options.append({"value": str(row["id"]), "label": label})
            return {"options": options, "next_page_token": None}
        finally:
            if reader: await reader.read()

    async def execute(self, inputs):
        cfg = self.config.config
        raw = self.node_data.get("credentials") or (self.config.credentials.model_dump() if self.config.credentials is not None else None)
        data = await freshen_linkwarden_credential(raw, credential_id=self.node_data.get("credential_id"), user_id=self.user_id, workflow_id=self.workflow_id, organization_id=self.organization_id, pool=self.node_data.get("_approval_pool"))
        value, reader = guard(data), data.get("_linkwarden_reader")
        try:
            if cfg.operation == "list_collections": return result_page(await request(value, "/collections", reader=reader), "collection", names=cfg.include_names)
            if cfg.operation == "list_tags": return result_page(await request(value, "/tags", reader=reader), "tag", names=cfg.include_names)
            if cfg.operation != "get_collection": raise ValueError("Unsupported Linkwarden metadata operation")
            selected = identifier(cfg.collection_id)
            before = catalog(await request(value, "/collections", reader=reader), "collection")
            if not any(r["id"] == selected for r in before): raise ValueError("Linkwarden selected collection is unavailable in the current catalog")
            payload = await request(value, f"/collections/{selected}", reader=reader)
            detail = record(payload.get("response"), "collection", names=cfg.include_names)
            if detail["id"] != selected: raise ValueError("Linkwarden returned a different collection ID")
            after = catalog(await request(value, "/collections", reader=reader), "collection")
            if not any(r["id"] == selected for r in after): raise ValueError("Linkwarden collection access changed during this call")
            return detail
        finally:
            if reader: await reader.read()
