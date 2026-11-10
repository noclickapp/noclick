"""Closed Rebrandly metadata reads with explicit workspace/domain ancestry.

Protected catalogs witness access, not principal identity or ownership. No link
URLs, destination data, account settings or mutating routes are exposed.
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
from repositories.rebrandly_credentials import fetch_snapshot
from utils.ssrf import guarded_async_client

ROOT = "https://api.rebrandly.com/v1"
TYPE = "rebrandly_api_key"
MAX_BYTES = 2 * 1024 * 1024
MAX_PAGES = 10
OPERATIONS = {"list_workspaces", "list_domains", "get_domain", "list_links", "get_link"}
ID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Supply a bounded opaque Rebrandly resource ID")
    return value


def text(value):
    if not isinstance(value, str) or len(value) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Rebrandly returned malformed scalar text")
    return value


class RebrandlyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, title="Rebrandly API Key", json_schema_extra={"x-credential-url": "https://developers.rebrandly.com/docs/api-key-authentication"})
    credential_type: Literal["rebrandly_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=8192, repr=False, title="API Key", description="Existing API key supplied only in the apikey header to api.rebrandly.com/v1. No token exchange, refresh or alternate enterprise host.", json_schema_extra={"ui:widget": "password"})
    workspace_id: ID = Field(..., title="Allowed Workspace ID", description="Explicit selected workspace. Every domain/link request includes this Workspace header; main workspace is never silently selected. Current protected workspace catalog membership is required.")

    @model_serializer(mode="wrap")
    def canonical(self, handler):
        return {**handler(self), "credential_type": TYPE}

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply the existing Rebrandly API key without whitespace")
        return value


def guard(data):
    if not isinstance(data, dict) or data.get("credential_type") != TYPE:
        raise ValueError("Connect a typed Rebrandly API key")
    try:
        return RebrandlyAPIKeyCredential.model_validate({k: v for k, v in data.items() if k not in {"_rebrandly_reader", "token_version", "updated_at"}})
    except ValueError:
        raise ValueError("Rebrandly credential shape is invalid; reconnect it") from None


def authority(value):
    return value.credential_type, value.workspace_id, value.api_key


async def current(credential_id, user_id, organization_id=None, workflow_id=None, *, pool=None):
    if not user_id:
        raise ValueError("Stored Rebrandly credentials require a caller")
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
        raise ValueError("Rebrandly credential is unavailable or has the wrong type/version")
    try:
        data = get_encryption().decrypt_credential(row["credential"])
    except Exception:
        raise ValueError("Rebrandly credential cannot be read") from None
    if not isinstance(data, dict) or data.get("credential_type") != row["credential_type"]:
        raise ValueError("Rebrandly saved credential type does not match its row")
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
            raise ValueError("Rebrandly cached credential changed; reload it")
        binding = (owner, version, *authority(value))
        if self.anchor is not None and binding != self.anchor:
            raise ValueError("Rebrandly saved credential changed during this call")
        self.anchor = binding
        return value


def op(value, title):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Metadata", "x-is-trigger": False})


def resource(name):
    parents = {"workspace_id": [], "domain_id": ["workspace_id"], "link_id": ["workspace_id", "domain_id"]}[name]
    return {"x-resource-type": "rebrandly_" + name.removesuffix("_id"), "x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True, **({"depends_on": parents} if parents else {})}}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    workspace_id: ID | None = Field(None, title="Workspace", description="Select the exact saved workspace. Omitted uses only the explicitly saved workspace ID, never the provider's default main workspace.", json_schema_extra=resource("workspace_id"))
    include_names: StrictBool = Field(False, title="Include Names", description="Opt in to workspace name, domain fullName and link title/slashtag. URLs, destinations, owners, account settings and billing are always omitted.")


class PageInput(Input):
    limit: Annotated[StrictInt, Field(ge=1, le=25)] = Field(25, title="Page Size", description="Explicit limit1..25. Workspace maximum is a local bound; domain/link limit is documented. No short-page completion or total inference.")
    page_token: str | None = Field(None, max_length=32768, title="Continuation", description="Native sealed preceding-page ID for domains/links only. A candidate next page is not proof that more records exist. At most ten caller-driven pages; no automatic paging.")


class ListWorkspaces(Input):
    operation: Literal["list_workspaces"] = op("list_workspaces", "List Workspace Metadata")
    limit: Annotated[StrictInt, Field(ge=1, le=25)] = Field(25, title="Page Size", description="Local1..25 bound, explicit offset0. Selected workspace access is independently witnessed in the current bounded25 catalog, no complete inventory inferred.")


class ListDomains(PageInput):
    operation: Literal["list_domains"] = op("list_domains", "List Domain Metadata")


class DomainInput(Input):
    domain_id: ID = Field(..., title="Domain", description="Exact current selected-workspace domain ID. Membership is checked in one bounded current catalog page; absence is not global nonexistence.", json_schema_extra=resource("domain_id"))


class GetDomain(DomainInput):
    operation: Literal["get_domain"] = op("get_domain", "Get Domain Metadata")


class ListLinks(DomainInput):
    operation: Literal["list_links"] = op("list_links", "List Link Metadata")
    limit: Annotated[StrictInt, Field(ge=1, le=25)] = Field(25, title="Page Size")
    page_token: str | None = Field(None, max_length=32768, title="Continuation", description="Use this operation's sealed preceding-page link ID, same workspace/domain/limit/name selection. No URL following or completion guarantee.")


class GetLink(DomainInput):
    operation: Literal["get_link"] = op("get_link", "Get Link Metadata")
    link_id: ID = Field(..., title="Link", description="Exact link ID from the current domain-filtered first catalog page with matching nested domain.id. Missing parent or a link outside this bounded page is unsupported, not inferred from URL/flat aliases.", json_schema_extra=resource("link_id"))


Config = Annotated[Union[ListWorkspaces, ListDomains, GetDomain, ListLinks, GetLink], Field(discriminator="operation")]


class RebrandlyNodeConfig(NodeConfig[Config, RebrandlyAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class PrivateHeaders(dict):
    def __repr__(self):
        return "<private Rebrandly apikey/workspace headers>"
    __str__ = __repr__


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated Rebrandly metadata field")
        result[key] = value
    return result


def invalid_number(_value):
    raise ValueError("Nonfinite Rebrandly metadata number")


async def request(value, endpoint, *, query=None, reader=None):
    query = query or {}
    if endpoint not in {"/workspaces", "/domains", "/links"} and re.fullmatch(r"/(?:domains|links)/[A-Za-z0-9_-]{1,128}", endpoint) is None:
        raise ValueError("Unsupported Rebrandly metadata route")
    if endpoint == "/workspaces":
        if set(query) != {"limit", "offset"} or any(type(v) is not int for v in query.values()) or not 1 <= query["limit"] <= 25 or query["offset"] != 0:
            raise ValueError("Rebrandly workspace catalog uses one explicit local1..25 page at offset0")
    elif endpoint in {"/domains", "/links"}:
        expected = {"limit"} | ({"last"} if "last" in query else set()) | ({"domain.id"} if endpoint == "/links" else set())
        if set(query) != expected or type(query.get("limit")) is not int or not 1 <= query["limit"] <= 25:
            raise ValueError("Supply only exact Rebrandly bounded metadata paging")
        if "last" in query: safe_id(query["last"])
        if endpoint == "/links": safe_id(query["domain.id"])
    elif query:
        raise ValueError("Rebrandly metadata points do not accept arbitrary query fields")
    if reader: value = await reader.read()
    headers = PrivateHeaders({"apikey": value.api_key, "Accept": "application/json", "Cache-Control": "no-store"})
    if endpoint != "/workspaces": headers["Workspace"] = value.workspace_id
    try:
        try:
            async with guarded_async_client(timeout=12, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", ROOT + endpoint, params=query, headers=headers) as response:
                    if response.status_code != 200 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError("Rebrandly metadata read refused or format unavailable")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES: raise ValueError("Rebrandly metadata exceeds the local2MiB bound")
            result = json.loads(raw, object_pairs_hook=unique_json, parse_constant=invalid_number)
            if not isinstance(result, list if endpoint in {"/workspaces", "/domains", "/links"} else dict):
                raise ValueError("Rebrandly returned a different array/object contract")
            return result
        except Exception:
            raise ValueError("Rebrandly metadata read could not be established; inspect supplied key, permissions, plan or service availability") from None
    finally:
        if reader: await reader.read()


def record(row, kind, *, names=False, workspace=None, domain=None):
    if not isinstance(row, dict): raise ValueError("Rebrandly metadata requires an object")
    result = {"id": safe_id(row.get("id"))}
    fields = {"workspace": {"default": bool, "createdAt": str}, "domain": {"createdAt": str, "updatedAt": str}, "link": {"createdAt": str, "updatedAt": str, "https": bool, "clicks": int}}[kind]
    if names: fields = {**fields, **{"workspace": {"name": str}, "domain": {"fullName": str}, "link": {"title": str, "slashtag": str}}[kind]}
    for key, expected in fields.items():
        if key not in row: continue
        value = row[key]
        if type(value) is not expected or (expected is int and value < 0): raise ValueError("Rebrandly returned malformed defined scalar metadata")
        result[key] = text(value) if expected is str else value
    if kind != "workspace" and "workspace" in row:
        if not isinstance(row["workspace"], dict) or safe_id(row["workspace"].get("id")) != workspace:
            raise ValueError("Rebrandly returned a different workspace witness")
    if kind == "domain":
        text(row.get("fullName"))  # Required current domain catalog/detail binding; private by default.
        if "status" in row:
            if not isinstance(row["status"], dict): raise ValueError("Malformed Rebrandly domain status")
            if "dns" in row["status"]:
                if not isinstance(row["status"]["dns"], str) or row["status"]["dns"] not in {"verified", "unverified", "verifying"}: raise ValueError("Unknown Rebrandly DNS state")
                result["dns_status"] = row["status"]["dns"]
    if kind == "link":
        if not isinstance(row.get("domain"), dict) or safe_id(row["domain"].get("id")) != domain:
            raise ValueError("Rebrandly link nested domain witness is unavailable or foreign")
        if not isinstance(row.get("status"), str) or row["status"] not in {"active", "deleted", "blocked"}: raise ValueError("Unknown or unavailable Rebrandly link state")
        result["status"] = row["status"]
    return result


def rows(payload, kind, limit, value, *, domain=None):
    if not isinstance(payload, list) or len(payload) > limit: raise ValueError("Rebrandly requires a bounded bare array")
    ids = [record(r, kind, workspace=value.workspace_id, domain=domain)["id"] for r in payload]
    if len(ids) != len(set(ids)): raise ValueError("Rebrandly metadata repeated a resource ID")
    return payload


def binding(value, kind, domain, limit, names, search=None):
    return {"workspace": value.workspace_id, "kind": kind, "domain": domain, "limit": limit, "names": names, "search": search}


def cipher(value):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(json.dumps(authority(value), separators=(",", ":")).encode()).digest()))


def continuation(value, token, bound):
    if token is None: return None, [], 0
    try:
        if not isinstance(token, str) or not 1 <= len(token) <= 32768: raise ValueError()
        data = json.loads(cipher(value).decrypt(token.encode()), object_pairs_hook=unique_json)
        if not isinstance(data, dict) or set(data) != {"binding", "last", "seen", "pages"} or data["binding"] != bound or type(data["pages"]) is not int or not 1 <= data["pages"] < MAX_PAGES or not isinstance(data["seen"], list) or not 1 <= len(data["seen"]) <= 25 * MAX_PAGES:
            raise ValueError()
        last = safe_id(data["last"]); seen = [safe_id(v) for v in data["seen"]]
        if last != seen[-1] or len(seen) != len(set(seen)): raise ValueError()
        return last, seen, data["pages"]
    except (ValueError, TypeError, UnicodeError, InvalidToken):
        raise ValueError("Rebrandly continuation is invalid or credential/parent/page/privacy/search changed") from None


def result_page(value, payload, kind, limit, names, token, *, domain=None, search=None):
    bound = binding(value, kind, domain, limit, names, search)
    _last, seen, pages = continuation(value, token, bound)
    payload = rows(payload, kind, limit, value, domain=domain)
    ids = [r["id"] for r in payload]
    if set(seen) & set(ids): raise ValueError("Rebrandly page repeated a preceding resource ID")
    capped = pages + 1 >= MAX_PAGES
    next_page = None
    if ids and not capped:
        next_page = cipher(value).encrypt(json.dumps({"binding": bound, "last": ids[-1], "seen": seen + ids, "pages": pages + 1}, separators=(",", ":")).encode()).decode()
    return {"items": [record(r, kind, names=names, workspace=value.workspace_id, domain=domain) for r in payload], "count": len(payload), "total": None, "has_more": None, "completion_verified": False, "snapshot_verified": False, "local_limit_reached": capped, "next_page_token": next_page, "continuation_is_candidate": bool(next_page)}


class RebrandlyNode(WorkflowNode):
    integration_type = "automation-rebrandly"
    credential_provider_labels = {"rebrandly": "Rebrandly Account"}
    auto_select_credential = False
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_workspaces", noun="selected workspace catalog metadata", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return RebrandlyNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._freshen_scoped_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def _freshen_scoped_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=None):
        value = guard(credential_data)
        if not credential_id: return value.model_dump()
        if not user_id: raise ValueError("Stored Rebrandly credentials require a caller")
        reader = Reader(credential_id, user_id, organization_id, workflow_id, pool, expected=authority(value))
        fresh = await reader.read()
        return {**fresh.model_dump(), "_rebrandly_reader": reader}

    @staticmethod
    def _selected(value, workspace):
        if workspace is not None and safe_id(workspace) != value.workspace_id:
            raise ValueError("Rebrandly workspace is outside the saved scope")

    @classmethod
    async def _workspace(cls, value, workspace, reader):
        cls._selected(value, workspace)
        catalog = rows(await request(value, "/workspaces", query={"limit": 25, "offset": 0}, reader=reader), "workspace", 25, value)
        if not any(r["id"] == value.workspace_id for r in catalog):
            raise ValueError("Selected Rebrandly workspace is absent from the bounded current catalog page; membership is not established")
        return catalog

    @classmethod
    async def _domain(cls, value, domain, reader):
        safe_id(domain)
        catalog = rows(await request(value, "/domains", query={"limit": 25}, reader=reader), "domain", 25, value)
        selected = next((r for r in catalog if r["id"] == domain), None)
        if selected is None: raise ValueError("Rebrandly domain is absent from the bounded current workspace page")
        detail = await request(value, f"/domains/{domain}", reader=reader)
        if record(detail, "domain", workspace=value.workspace_id)["id"] != domain or detail["fullName"] != selected["fullName"]:
            raise ValueError("Rebrandly returned a different current domain ID/name binding")
        return detail

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        value = guard(credential_data); reader = credential_data.get("_rebrandly_reader")
        if reader is not None and not isinstance(reader, Reader): raise ValueError("Invalid Rebrandly current-row reader")
        context = context or {}; search = search or ""
        if not isinstance(search, str) or len(search) > 256: raise ValueError("Supply a bounded Rebrandly picker search")
        names = context.get("include_names") is True
        try:
            workspace = context.get("workspace_id")
            if field_name != "workspace_id" and not workspace: raise ValueError("Select the saved Rebrandly workspace before loading children")
            cls._selected(value, workspace)
            if field_name not in {"workspace_id", "domain_id", "link_id"}: raise ValueError("Unsupported Rebrandly metadata picker")
            kind = "domain" if field_name == "domain_id" else "link"
            domain = None
            if field_name == "workspace_id" and page_token: raise ValueError("Rebrandly workspace picker uses only the bounded offset0 page")
            if field_name == "link_id":
                if not context.get("domain_id"): raise ValueError("Select a Rebrandly domain before loading links")
                domain = safe_id(context["domain_id"])
            bound = binding(value, kind, domain, 25, names, search)
            last, _seen, _pages = continuation(value, page_token, bound) if field_name != "workspace_id" else (None, [], 0)
            catalog = await cls._workspace(value, workspace, reader)
            if field_name == "workspace_id":
                if page_token: raise ValueError("Rebrandly workspace picker uses only the bounded offset0 page")
                selected = next(r for r in catalog if r["id"] == value.workspace_id)
                label = text(selected["name"]) if names and "name" in selected else "Saved workspace"
                return {"options": [{"value": value.workspace_id, "label": label}] if search.casefold() in (value.workspace_id + " " + label).casefold() else [], "next_page_token": None}
            if kind == "link": await cls._domain(value, domain, reader)
            query = {"limit": 25, **({"last": last} if last else {}), **({"domain.id": domain} if domain else {})}
            payload = await request(value, "/domains" if kind == "domain" else "/links", query=query, reader=reader)
            page = result_page(value, payload, kind, 25, names, page_token, domain=domain, search=search)
            if page["local_limit_reached"] and payload: raise ValueError("Rebrandly picker reaches the local ten-page bound; completeness unknown")
            options = []
            for row in page["items"]:
                label = row.get("fullName") or row.get("title") or row.get("slashtag") or f"{'Domain' if kind == 'domain' else 'Link'} {row['id']}"
                if search.casefold() in (row["id"] + " " + label).casefold(): options.append({"value": row["id"], "label": label})
            return {"options": options, "next_page_token": page["next_page_token"]}
        finally:
            if reader: await reader.read()

    async def execute(self, inputs):
        cfg = self.config.config
        raw = self.node_data.get("credentials") or (self.config.credentials.model_dump() if self.config.credentials is not None else None)
        data = await self._freshen_scoped_credential(raw, credential_id=self.node_data.get("credential_id"), user_id=self.user_id, workflow_id=self.workflow_id, organization_id=self.organization_id, pool=self.node_data.get("_approval_pool"))
        value, reader = guard(data), data.get("_rebrandly_reader")
        try:
            if cfg.operation not in OPERATIONS: raise ValueError("Unsupported Rebrandly metadata operation")
            self._selected(value, cfg.workspace_id)
            if cfg.operation in {"list_domains", "list_links"}:
                kind, selected = ("domain", None) if cfg.operation == "list_domains" else ("link", cfg.domain_id)
                bound = binding(value, kind, selected, cfg.limit, cfg.include_names)
                last, _seen, _pages = continuation(value, cfg.page_token, bound)
            catalog = await self._workspace(value, cfg.workspace_id, reader)
            if cfg.operation == "list_workspaces":
                if cfg.limit != 25: catalog = rows(await request(value, "/workspaces", query={"limit": cfg.limit, "offset": 0}, reader=reader), "workspace", cfg.limit, value)
                return {"items": [record(r, "workspace", names=cfg.include_names) for r in catalog], "count": len(catalog), "total": None, "has_more": None, "completion_verified": False, "snapshot_verified": False, "selected_workspace_access_witnessed": True, "principal_identity_verified": False, "workspace_ownership_verified": False}
            if cfg.operation in {"get_domain", "list_links", "get_link"}: domain = await self._domain(value, cfg.domain_id, reader)
            if cfg.operation == "get_domain": return record(domain, "domain", names=cfg.include_names, workspace=value.workspace_id)
            if cfg.operation in {"list_domains", "list_links"}:
                query = {"limit": cfg.limit, **({"last": last} if last else {}), **({"domain.id": selected} if selected else {})}
                payload = await request(value, "/domains" if kind == "domain" else "/links", query=query, reader=reader)
                return result_page(value, payload, kind, cfg.limit, cfg.include_names, cfg.page_token, domain=selected)
            links = rows(await request(value, "/links", query={"limit": 25, "domain.id": cfg.domain_id}, reader=reader), "link", 25, value, domain=cfg.domain_id)
            if not any(r["id"] == cfg.link_id for r in links): raise ValueError("Rebrandly link is absent from the bounded current domain page")
            link = await request(value, f"/links/{cfg.link_id}", reader=reader)
            if record(link, "link", workspace=value.workspace_id, domain=cfg.domain_id)["id"] != cfg.link_id: raise ValueError("Rebrandly returned a different selected link")
            return record(link, "link", names=cfg.include_names, workspace=value.workspace_id, domain=cfg.domain_id)
        finally:
            if reader: await reader.read()
