"""Native IONOS Cloud datacenter and server metadata reads.

Supplied Bearer tokens and optional contract selection remain header bound.
Protected ancestry and strict projection fence each read. Credentials are loaded
by the shared credential resolver; supplied tokens do not need refresh.
"""
from datetime import datetime
import base64
import hashlib
import hmac
import json
import re
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

FAMILY = "ionoscloud_bearer"
NODE_TYPE = "automation-ionoscloud"
ROOT = "https://api.ionos.com/cloudapi/v6"
OPS = ("check_connection", "list_datacenters", "get_datacenter", "list_servers", "get_server")
MAX_OFFSET = 2**31 - 1
WITNESS_PAGES = 10


def resource_id(value):
    # The OAS resource/path ID is a string; UUID examples do not impose a format.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("Enter a single IONOS resource ID without a URL or whitespace")
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


def approved_datacenters(value):
    if not isinstance(value, str) or len(value) > 8000: raise ValueError("Enter approved datacenter IDs as a JSON string array")
    raw = strict_json(value)
    if not isinstance(raw, list) or len(raw) > 50: raise ValueError("Approve at most 50 existing datacenters")
    ids = [resource_id(item) for item in raw]
    if len(set(ids)) != len(ids): raise ValueError("Approve distinct datacenter IDs")
    return ids


class IONOSCloudBearerCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="IONOS Cloud Bearer Token",
        json_schema_extra={"x-credential-instructions": "Enter an existing Cloud API Bearer token and approved existing datacenter IDs. Supply a contract number only when your existing account requires one. Protected catalog access does not identify a principal or prove ownership.", "x-help-url": "https://api.ionos.com/docs/cloud/v6/"})
    credential_type: Literal["ionoscloud_bearer"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    token: str = Field(..., title="Bearer Token", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    contract_number: Optional[int] = Field(None, strict=True, ge=-(2**31), le=MAX_OFFSET, title="Contract Number", description="Optional exact existing X-Contract-Number integer. Bound to every request; no contract fallback.")
    approved_datacenter_ids_json: str = Field("[]", title="Approved Datacenter IDs", description='JSON string array of existing resource IDs, at most 50. Example: ["15f67991-0f51-4efc-a8ad-ef1fb31a480c"].', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    include_labels: bool = Field(False, strict=True, title="Include Resource Names", description="Opt in to datacenter/server names only. All links, entities, hostnames, users, network, boot and configuration data remain excluded.")
    @field_validator("token")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Bearer Token")
        if not value or len(value) > 8192 or value.lower().startswith(("basic ", "bearer ", "token ")) or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Enter the issued Bearer token without a header prefix or whitespace")
        return value
    @field_validator("approved_datacenter_ids_json")
    @classmethod
    def allowed(cls, value):
        approved_datacenters(value)
        return value


def credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != FAMILY: raise ValueError("Connect a native IONOS Cloud supplied Bearer token")
    if any(key in data for key in ("username", "password", "api_key", "api_secret", "access_token", "refresh_token", "base_url", "host", "cookie", "client_id")):
        raise ValueError("Use only the native supplied IONOS Cloud Bearer form")
    try: return IONOSCloudBearerCredential.model_validate(data).model_dump()
    except ValueError: raise ValueError("Complete the native IONOS Cloud token, contract and datacenter form") from None


def headers(now):
    result = {"Authorization": "Bearer " + now["token"]}
    if now["contract_number"] is not None: result["X-Contract-Number"] = str(now["contract_number"])
    return result


def dynamic(field, parent=None):
    return {"x-resource-type": "ionoscloud_" + field.removesuffix("_id"),
        "x-dynamic-options": {"field_name": field, "searchable": True, "allow_custom": True,
                             **({"depends_on": parent} if parent else {})}}


class NativeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CheckConnection(NativeModel):
    operation: Literal["check_connection"] = "check_connection"


class Page(NativeModel):
    offset: int = Field(0, strict=True, ge=0, le=MAX_OFFSET, description="Documented zero-based offset. Each operation returns one bounded provider page.")
    limit: int = Field(50, strict=True, ge=1, le=100, description="Explicit provider page size, locally limited to 100. No total count is inferred.")


class ListDatacenters(Page):
    operation: Literal["list_datacenters"] = "list_datacenters"


class DatacenterSelection(NativeModel):
    datacenter_id: str = Field(..., title="Datacenter", json_schema_extra=dynamic("datacenter_id"))
    @field_validator("datacenter_id")
    @classmethod
    def selected(cls, value): return resource_id(value)


class GetDatacenter(DatacenterSelection):
    operation: Literal["get_datacenter"] = "get_datacenter"


class ListServers(DatacenterSelection, Page):
    operation: Literal["list_servers"] = "list_servers"


class GetServer(DatacenterSelection):
    operation: Literal["get_server"] = "get_server"
    server_id: str = Field(..., title="Server", json_schema_extra=dynamic("server_id", "datacenter_id"))
    @field_validator("server_id")
    @classmethod
    def selected_server(cls, value): return resource_id(value)


Operation = Annotated[Union[CheckConnection, ListDatacenters, GetDatacenter, ListServers, GetServer], Field(discriminator="operation")]


class IONOSCloudNodeConfig(NodeConfig[Operation, IONOSCloudBearerCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class Projection(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class Metadata(Projection):
    state: Optional[Literal["AVAILABLE", "INACTIVE", "BUSY", "DEPLOYING", "ACTIVE", "FAILED", "SUSPENDED",
        "FAILED_SUSPENDED", "UPDATING", "FAILED_UPDATING", "DESTROYING", "FAILED_DESTROYING", "TERMINATED",
        "HIBERNATING", "FAILED_HIBERNATING", "MAINTENANCE", "FAILED_MAINTENANCE", "UNKNOWN"]] = None
    createdDate: Optional[str] = Field(None, max_length=100)
    lastModifiedDate: Optional[str] = Field(None, max_length=100)
    @field_validator("createdDate", "lastModifiedDate")
    @classmethod
    def date(cls, value):
        if value is not None:
            try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError: raise ValueError("Unverified resource date") from None
            if parsed.tzinfo is None: raise ValueError("Unverified resource date")
        return value


class DatacenterProperties(Projection):
    location: Optional[str] = Field(None, max_length=100)
    version: Optional[int] = Field(None, ge=0, le=MAX_OFFSET)
    name: Optional[str] = Field(None, max_length=500, exclude=True)


class ServerProperties(Projection):
    type: Optional[Literal["CUBE", "ENTERPRISE", "VCPU", "GPU"]] = None
    vmState: Optional[Literal["NOSTATE", "RUNNING", "BLOCKED", "PAUSED", "SHUTDOWN", "SHUTOFF", "CRASHED", "SUSPENDED"]] = None
    name: Optional[str] = Field(None, max_length=500, exclude=True)


class Resource(Projection):
    id: str
    metadata: Optional[Metadata] = None
    @field_validator("id")
    @classmethod
    def valid_id(cls, value): return resource_id(value)


class Datacenter(Resource):
    type: Literal["datacenter"]
    properties: Optional[DatacenterProperties] = None


class Server(Resource):
    type: Literal["server"]
    properties: Optional[ServerProperties] = None

async def current_credential(data):
    return credential(data)


async def request(data, path, *, params=None):
    now = await current_credential(data)
    try:
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", ROOT + path, headers={**headers(now),
                "Accept": "application/json", "Content-Type": "application/json"}, params=params) as response:
                await current_credential(data)
                status = response.status_code
                if status in {400, 401, 403, 404, 422}: raise ValueError(f"IONOS Cloud refused the metadata read (HTTP {status})")
                if status != 200: raise RuntimeError(f"IONOS Cloud metadata read did not complete (HTTP {status}); no automatic retry")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json": raise RuntimeError("IONOS Cloud returned an unexpected response type")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000: raise RuntimeError("IONOS Cloud response exceeds the native metadata limit")
                await current_credential(data)
    except httpx.HTTPError: raise RuntimeError("IONOS Cloud metadata transport did not complete; no automatic retry") from None
    try: return strict_json(bytes(content))
    except ValueError: raise RuntimeError("IONOS Cloud returned invalid JSON") from None


def typed(model, raw):
    try: return model.model_validate(raw)
    except ValueError: raise RuntimeError("IONOS Cloud returned unverified resource metadata") from None


def page(model, raw, offset, limit):
    if not isinstance(raw, dict) or raw.get("type") != "collection" or not isinstance(raw.get("items"), list):
        raise RuntimeError("IONOS Cloud returned an unverified collection envelope")
    if len(raw["items"]) > limit: raise RuntimeError("IONOS Cloud exceeded the requested page bound")
    for key, expected in (("offset", offset), ("limit", limit)):
        # OAS echoes are numbers, not necessarily integer-valued JSON literals.
        if key in raw and (type(raw[key]) not in (int, float) or raw[key] != expected):
            raise RuntimeError("IONOS Cloud returned an unexpected page boundary")
    links = raw.get("_links", {})
    if not isinstance(links, dict): raise RuntimeError("IONOS Cloud returned unverified pagination metadata")
    # Only key presence is used. Its value is never accessed, exposed or followed.
    has_more = "next" in links
    rows = [typed(model, item) for item in raw["items"]]
    if len({row.id for row in rows}) != len(rows): raise RuntimeError("IONOS Cloud repeated a resource ID within one page")
    if has_more and len(rows) != limit: raise RuntimeError("IONOS Cloud returned an incomplete page with a continuation")
    if has_more and offset > MAX_OFFSET - limit: raise RuntimeError("IONOS Cloud continuation exceeds the native offset bound")
    return rows, has_more


def output(row, now):
    result = row.model_dump(exclude_none=True)
    if now["include_labels"] and row.properties is not None and row.properties.name is not None:
        result.setdefault("properties", {})["name"] = row.properties.name
    return result


def selected_datacenter(now, value):
    value = resource_id(value)
    if value not in approved_datacenters(now["approved_datacenter_ids_json"]):
        raise ValueError("Datacenter is outside the saved approved-ID restriction")
    return value


async def catalog_page(data, model, path, offset, limit):
    return page(model, await request(data, path, params={"depth": 1, "offset": offset, "limit": limit}), offset, limit)


async def find_catalog_resource(data, model, path, value):
    offset = 0
    seen = set()
    for _ in range(WITNESS_PAGES):
        rows, has_more = await catalog_page(data, model, path, offset, 100)
        ids = {row.id for row in rows}
        if seen & ids: raise RuntimeError("IONOS Cloud repeated catalog IDs across the bounded witness scan")
        seen.update(ids)
        if value in ids: return
        if not has_more: raise ValueError("Selected resource was not returned by the current protected catalog; ownership and global absence are unverified")
        offset += 100
    raise ValueError("IONOS Cloud ancestry witness exceeds the bounded catalog scan; completion is unverified")


async def datacenter_witness(data, value):
    now = await current_credential(data)
    selected = selected_datacenter(now, value)
    await find_catalog_resource(data, Datacenter, "/datacenters", selected)
    row = typed(Datacenter, await request(data, "/datacenters/" + selected, params={"depth": 0}))
    if row.id != selected: raise RuntimeError("IONOS Cloud detail did not confirm its selected catalog datacenter")
    await current_credential(data)
    return row


async def server_witness(data, dc, value):
    selected = resource_id(value)
    path = "/datacenters/" + dc + "/servers"
    await find_catalog_resource(data, Server, path, selected)
    row = typed(Server, await request(data, path + "/" + selected, params={"depth": 0}))
    if row.id != selected: raise RuntimeError("IONOS Cloud server detail did not confirm its selected parent catalog resource")
    await current_credential(data)
    return row


def list_result(rows, now, offset, limit, has_more, *, received_count, filtered_count=0, parent=None):
    result = {"status": "success", "results": [output(row, now) for row in rows],
        "offset": offset, "limit": limit, "received_count": received_count, "returned_count": len(rows),
        "filtered_count": filtered_count, "has_more": has_more, "next_offset": offset + limit if has_more else None,
        "page_complete": True, "resource_access_verified": True, "identity_verified": False,
        "account_ownership_verified": False, "contract_number": now["contract_number"]}
    if parent is not None: result.update(datacenter_id=parent, parent_link_verified=True)
    return result


async def list_datacenters(data, offset, limit):
    now = await current_credential(data)
    allowed = approved_datacenters(now["approved_datacenter_ids_json"])
    if not allowed: raise ValueError("Approve existing datacenter IDs before listing datacenters")
    rows, more = await catalog_page(data, Datacenter, "/datacenters", offset, limit)
    projected = [row for row in rows if row.id in allowed]
    await current_credential(data)
    return list_result(projected, now, offset, limit, more, received_count=len(rows), filtered_count=len(rows) - len(projected))


def cursor_binding(data, field, parent, search, limit):
    now = credential(data)
    return {"version": 1, "field": field, "parent": parent, "search": search, "limit": limit,
        "contract": now["contract_number"], "approved": now["approved_datacenter_ids_json"], "labels": now["include_labels"]}



def cursor(data, field, parent, search, limit, offset, supplied=None):
    binding = cursor_binding(data, field, parent, search, limit)
    key = credential(data)["token"].encode("utf-8")
    def signature(number):
        encoded = json.dumps({"binding": binding, "offset": number}, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(key, encoded, hashlib.sha256).hexdigest()
    if supplied is not None:
        try:
            if not isinstance(supplied, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,500}", supplied): raise ValueError()
            raw = strict_json(base64.urlsafe_b64decode(supplied + "=" * (-len(supplied) % 4)))
            if not isinstance(raw, dict) or set(raw) != {"offset", "seal"}: raise ValueError()
            number = raw["offset"]
            if type(number) is not int or number < 1 or number > MAX_OFFSET or number % limit: raise ValueError()
            if not isinstance(raw["seal"], str) or not hmac.compare_digest(raw["seal"], signature(number)): raise ValueError()
            return number
        except (ValueError, TypeError, UnicodeError): raise ValueError("IONOS Cloud picker continuation no longer matches its saved credential, parent or search") from None
    raw = json.dumps({"offset": offset, "seal": signature(offset)}, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class IONOSCloudNode(WorkflowNode):
    integration_type = "automation-ionoscloud"
    connection_evidence = ConnectionEvidence(identity_operation="check_connection", noun="IONOS Cloud datacenter catalog access",
        label_keys=(), identity_keys=(), proves="reachability")
    scope_registry = ScopeRegistry(provider="ionoscloud", enforcement=Enforcement.STRICT,
        requirements={op: ScopeRequirement(scopes=(), credential_types=(FAMILY,), note="Existing Bearer token at the fixed Cloud API v6 origin, with optional exact saved X-Contract-Number. Current provider acceptance and saved datacenter restriction govern access. No principal, account ownership, issued token permission or OAuth scope is inferred.") for op in OPS})
    edit_examples = ["Read metadata for an approved IONOS datacenter", "List server states under an approved datacenter", "Get status for a server returned by its current parent catalog"]
    @classmethod
    def get_config_model(cls): return IONOSCloudNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None: credential(config_data["credentials"])
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: credential(config_data["credentials"])
            except ValueError: return {"valid": False, "errors": ["Complete the native IONOS Cloud credential form"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        now = await current_credential(credential_data)
        if field_name not in ("datacenter_id", "server_id"): return {"options": [], "next_page_token": None}
        parent = None
        if field_name == "server_id":
            parent = selected_datacenter(now, (context or {}).get("datacenter_id"))
        term = (normalize_search(search) or "").casefold()
        offset = cursor(credential_data, field_name, parent, term, 100, 0, supplied=page_token) if page_token is not None else 0
        if parent is not None: await datacenter_witness(credential_data, parent)
        if field_name == "datacenter_id":
            result = await list_datacenters(credential_data, offset, 100)
        else:
            rows, more = await catalog_page(credential_data, Server, "/datacenters/" + parent + "/servers", offset, 100)
            result = list_result(rows, now, offset, 100, more, received_count=len(rows), parent=parent)
        options = [{"value": row["id"], "label": row.get("properties", {}).get("name") or row["id"],
            "metadata": {"parent_id": parent, "identity_verified": False}} for row in result["results"]]
        if term: options = [row for row in options if term in (row["value"] + " " + row["label"]).casefold()]
        await current_credential(credential_data)
        token = cursor(credential_data, field_name, parent, term, 100, result["next_offset"]) if result["has_more"] else None
        return {"options": options, "next_page_token": token, "has_more": result["has_more"], "search_scope": "current provider page"}

    async def execute(self, inputs: dict) -> dict:
        if not isinstance(self.config, IONOSCloudNodeConfig):
            raise ValueError("IONOS Cloud configuration is required")
        if self.config.credentials is None:
            raise ValueError("Connect an IONOS Cloud Bearer token")
        data = credential(self.config.credentials.model_dump())
        cfg = self.config.config
        now = await current_credential(data)
        if isinstance(cfg, CheckConnection):
            rows, more = await catalog_page(data, Datacenter, "/datacenters", 0, 1)
            await current_credential(data)
            return {"status": "success", "witness_verified": True, "received_count": len(rows), "has_more": more,
                "resource_access_verified": True, "identity_verified": False, "account_ownership_verified": False,
                "contract_number": now["contract_number"]}
        if isinstance(cfg, ListDatacenters): return await list_datacenters(data, cfg.offset, cfg.limit)
        row = await datacenter_witness(data, cfg.datacenter_id)
        if isinstance(cfg, GetDatacenter):
            await current_credential(data)
            return {"status": "success", "data": output(row, now), "catalog_link_verified": True,
                "resource_access_verified": True, "identity_verified": False, "account_ownership_verified": False,
                "contract_number": now["contract_number"]}
        if isinstance(cfg, ListServers):
            rows, more = await catalog_page(data, Server, "/datacenters/" + cfg.datacenter_id + "/servers", cfg.offset, cfg.limit)
            await current_credential(data)
            return list_result(rows, now, cfg.offset, cfg.limit, more, received_count=len(rows), parent=cfg.datacenter_id)
        server = await server_witness(data, row.id, cfg.server_id)
        await current_credential(data)
        return {"status": "success", "data": output(server, now), "datacenter_id": row.id, "parent_link_verified": True,
            "catalog_link_verified": True, "resource_access_verified": True, "identity_verified": False,
            "account_ownership_verified": False, "contract_number": now["contract_number"]}
