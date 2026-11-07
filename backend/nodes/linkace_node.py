"""LinkAce v2 list and tag metadata with supplied user-token authority.
Independent current catalogs witness access, never actor or account ownership.
"""
import ipaddress
import json
import re
from datetime import datetime
from typing import Annotated, Any, Dict, Literal, Union
from urllib.parse import urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client, normalize_https_origin

MAX_BYTES, MAX_ROWS = 2 * 1024 * 1024, 10000


def _text(value, limit=255):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value) or re.search(r"(?:https?|ssh|sftp)://", value, re.I): raise ValueError("Use bounded text without controls or URLs")
    return value


def _integer(value, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= 2**53 - 1: raise ValueError("Expected exact bounded metadata integer")
    return value


def _selected_id(value):
    if type(value) is int: return str(_integer(value, True))
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,15}", value): raise ValueError("Use a current positive numeric resource ID")
    _integer(int(value), True)
    return value


def _object(value):
    if not isinstance(value, dict): raise ValueError("Expected documented LinkAce JSON object")
    return value


def _date(value, nullable=False):
    if value is None and nullable: return None
    value = _text(value, 64)
    try:
        if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None: raise ValueError()
    except ValueError: raise ValueError("Expected raw ISO8601 metadata date") from None
    return value


def _origin(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value): raise ValueError("Use a bounded public HTTPS origin")
    try:
        origin = normalize_https_origin(value, field_name="LinkAce instance"); host = urlsplit(origin).hostname
        try: ipaddress.ip_address(host)
        except ValueError: pass
        else: raise ValueError("IP literals are unsupported")
        if not host or "." not in host or host.endswith((".localhost", ".local", ".internal")): raise ValueError()
        return origin
    except (ValueError, SSRFError): raise ValueError("Use one public HTTPS LinkAce origin without userinfo, path, query or fragment") from None


class LinkAceUserTokenCredential(BaseModel):
    model_config = ConfigDict(title="LinkAce User API Token", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://www.linkace.org/docs/v2/configuration/user-api-tokens/", "x-credential-instructions": "Supply an existing USER API token and one public HTTPS instance. Bearer header only, fixed /api/v2. No system/admin token, user lookup, token issue/refresh, Basic/OAuth or host fallback. User-token kind is a supplied declaration, not introspected identity; list access proves reachability only. Permissions, entitlement and installed v2 compatibility are unknown."})
    credential_type: Literal["linkace_user_token"] = Field("linkace_user_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., repr=False, title="Existing User API Token", json_schema_extra={"ui:widget": "password"})
    instance_url: str = Field(..., title="Public HTTPS LinkAce Instance Origin")
    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = _text(value, 4096)
        if any(c.isspace() for c in value): raise ValueError("Supply raw user token without prefix or whitespace")
        return clean_secret(value, field_name="LinkAce user API token")
    @field_validator("instance_url", mode="before")
    @classmethod
    def instance(cls, value): return _origin(value)


def _credential(raw):
    if isinstance(raw, LinkAceUserTokenCredential): raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("credential_type") != "linkace_user_token": raise ValueError("Select the authoritative LinkAce user-token family")
    raw = dict(raw)
    if "token_version" in raw and (type(raw["token_version"]) is not int or raw["token_version"] < 1): raise ValueError("Unsupported saved credential version")
    raw.pop("token_version", None); raw.pop("updated_at", None)
    if set(raw) != {"credential_type", "access_token", "instance_url"}: raise ValueError("Explicit user-token/public-instance grant required; no other auth family")
    try: return LinkAceUserTokenCredential.model_validate(raw)
    except Exception: raise ValueError("LinkAce supplied user-token/public-instance binding unsupported") from None


def _stored(raw): return _credential(raw).model_dump(mode="json")


def _op(value, title): return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "LinkAce Metadata", "x-is-trigger": False})


class _Catalog(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    include_names: bool = Field(False, strict=True, title="Include Private List and Tag Names", description="Names are opt-in. IDs remain available for independent current catalog selection; links and user IDs are always excluded.")
    per_page: int = Field(20, strict=True, ge=1, le=100, title="Local Page Size", description="Only per_page is sent. Default20 and bound1..100 are local; server defaults/caps unknown. Unlimited -1, undeclared page and ordering are excluded.")


class LinkAceListsConfig(_Catalog):
    operation: Literal["list_lists"] = _op("list_lists", "Read Accessible List Metadata")


class LinkAceListConfig(_Catalog):
    operation: Literal["get_list"] = _op("get_list", "Get Current List Metadata")
    list_id: str = Field(..., title="Current List ID", json_schema_extra={"x-resource-type": "list_id", "x-dynamic-options": {"field_name": "list_id", "allow_custom": True, "auto_select_sole_option": False}})
    @field_validator("list_id", mode="before")
    @classmethod
    def selected_list(cls, value): return _selected_id(value)


class LinkAceTagsConfig(_Catalog):
    operation: Literal["list_tags"] = _op("list_tags", "Read Accessible Tag Metadata")


class LinkAceTagConfig(_Catalog):
    operation: Literal["get_tag"] = _op("get_tag", "Get Current Tag Metadata")
    tag_id: str = Field(..., title="Current Tag ID", json_schema_extra={"x-resource-type": "tag_id", "x-dynamic-options": {"field_name": "tag_id", "allow_custom": True, "auto_select_sole_option": False}})
    @field_validator("tag_id", mode="before")
    @classmethod
    def selected_tag(cls, value): return _selected_id(value)


LinkAceOperation = Annotated[Union[LinkAceListsConfig, LinkAceListConfig, LinkAceTagsConfig, LinkAceTagConfig], Field(discriminator="operation")]
class LinkAceNodeConfig(NodeConfig[LinkAceOperation, LinkAceUserTokenCredential]):
    model_config = ConfigDict(title="LinkAce Node Configuration", hide_input_in_errors=True)


def _projected(raw, names=False):
    row = _object(raw); identifier = _integer(row.get("id"), True); out = {"id": identifier}
    if "visibility" in row:
        if _integer(row["visibility"]) not in {1, 2, 3}: raise ValueError("Expected documented visibility integer1..3")
        out["visibility"] = row["visibility"]
    for field in ("created_at", "updated_at", "deleted_at"):
        if field in row: out[field] = _date(row[field], field == "deleted_at")
    if names and "name" in row: out["name"] = _text(row["name"], 1024)
    return out, identifier


def _paging(raw, count, exposed, config):
    out = {f: _integer(raw[f], f in {"current_page", "last_page"}) for f in ("total", "from", "to", "last_page", "current_page") if f in raw}
    if "per_page" in raw: out["per_page"] = _text(raw["per_page"], 64)
    flags = {}
    for field, label in (("next_page_url", "next_page_url_present"), ("prev_page_url", "previous_page_url_present")):
        if field in raw:
            value = raw[field]
            if value is not None and (not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value)): raise ValueError("Expected nullable bounded internal pagination URL witness")
            flags[label] = value is not None
    truncated = count > config.per_page
    complete = None
    if {"current_page", "last_page"} <= out.keys():
        if out["current_page"] > out["last_page"]: raise ValueError("Incoherent typed current pagination witness")
        complete = out["current_page"] == out["last_page"]
    if flags.get("next_page_url_present") is True and complete is not None: complete = False
    if truncated: complete = None
    return {"pagination": out, **flags, "returned_count": count, "exposed_count": exposed, "local_truncated": truncated, "has_more": None if complete is None else not complete, "pagination_complete": complete, "next_page_token": None, "count_scope": "current_user_token_visible_collection", "global_coverage_proven": False}


class _ProviderError(Exception):
    def __init__(self, result): self.result = result


class _Session:
    def __init__(self, raw, config): self.raw, self.key, self.config, self.attempted, self.status = raw, _credential(raw), config, False, None
    def error(self, message): return {"status": "error", "action": self.config.operation, "error": message, "executed": self.attempted, "mutation_attempted": False, "_halt_downstream": True, **({"http_status": self.status} if self.status is not None else {})}
    async def request(self, kind, identifier=None):
        if kind not in {"lists", "tags"}: raise ValueError("Closed LinkAce metadata route required")
        path, params = "/api/v2/" + kind, {"per_page": str(self.config.per_page)}
        if identifier is not None: path += "/" + _selected_id(identifier); params = {}
        try:
            key = _credential(self.raw); self.status = None
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                async with client.stream("GET", key.instance_url + path, params=params, headers={"Authorization": "Bearer " + key.access_token, "Accept": "application/json"}) as response:
                    self.status = response.status_code; headers = response.headers; body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_BYTES: raise ValueError("LinkAce response exceeds local byte bound")
                        body.extend(chunk)
            if self.status != 200:
                reason = {401: "User-token authentication failed; cause is ambiguous", 403: "Permission is unverified", 404: "Resource is missing-or-invisible", 429: "Rate limit prevents verification"}.get(self.status, "Protected metadata access could not be verified")
                raise _ProviderError(self.error(reason + "; private provider bodies omitted; no retry or fallback"))
            if "application/json" not in headers.get("content-type", "").lower(): raise ValueError("Expected LinkAce JSON representation")
            return _object(json.loads(body))
        except (httpx.HTTPError, SSRFError): raise _ProviderError(self.error("LinkAce transport outcome unknown; no retry or fallback")) from None
    async def catalog(self, kind):
        raw = await self.request(kind); rows = raw.get("data")
        if not isinstance(rows, list) or len(rows) > MAX_ROWS: raise ValueError("Expected locally bounded documented data ARRAY")
        parsed = [_projected(row, self.config.include_names) for row in rows[:self.config.per_page]]; identifiers = [i for _, i in parsed]
        if len(set(identifiers)) != len(identifiers): raise ValueError("Ambiguous current independent catalog IDs")
        return {"data": [r for r, _ in parsed], **_paging(raw, len(rows), len(parsed), self.config)}, identifiers


class LinkAceNode(WorkflowNode):
    integration_type = "automation-linkace"
    credential_provider_labels = {"linkace": "LinkAce"}
    connection_evidence = ConnectionEvidence(operation="list_lists", noun="LinkAce protected list catalog", proves="reachability")
    edit_examples = ["Read current list visibility and timestamps without any bookmarked links", "Read independent tag metadata without revealing private names or user IDs"]
    @classmethod
    def get_config_model(cls): return LinkAceNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: _stored(config_data["credentials"])
            except ValueError as error: raise ConfigValidationError(str(error)) from None
        return super().parse_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Staging resolves saved credential access before dispatch; supplied tokens do not refresh.
        return _stored(credential_data)
    @classmethod
    async def validate_credential_access(cls, credential_data):
        try: _stored(credential_data)
        except ValueError: return {"valid": False, "error": "LinkAce user-token/public-instance family unsupported"}
        return {"valid": None, "error": "Run Read Accessible List Metadata to verify protected catalog reachability."}
    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config)
        try:
            kind = "lists" if config.operation in {"list_lists", "get_list"} else "tags" if config.operation in {"list_tags", "get_tag"} else None
            if kind is None: raise ValueError("Closed native operation required")
            out, identifiers = await session.catalog(kind)
            if config.operation in {"get_list", "get_tag"}:
                selected = int(config.list_id if kind == "lists" else config.tag_id)
                if selected not in identifiers: raise ValueError("Selection not on current bounded independent catalog; no global absence claim")
                row, identifier = _projected(await session.request(kind, selected), config.include_names)
                if identifier != selected: raise ValueError("Detail ID differs from current route/catalog witness")
                out = {"data": row}
                if selected not in (await session.catalog(kind))[1]: raise ValueError("Selection left current independent catalog")
            elif set((await session.catalog(kind))[1]) != set(identifiers): raise ValueError("Current independent catalog IDs changed")
            if session.key.access_token in json.dumps(out, ensure_ascii=False, allow_nan=False): raise ValueError("Output contains credential material")
            return {"status": "success", "action": config.operation, "executed": True, "http_status": session.status, "mutation_attempted": False, "snapshot_stable": False, "protected_reachability_verified": True, "principal_identity_proven": False, "instance_ownership_proven": False, **out}
        except _ProviderError as error: return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError): return session.error("Current saved credential/independent catalog or typed metadata could not be established; no raw fallback/retry")
    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        _credential(credential_data); context = context or {}
        if field_name not in {"list_id", "tag_id"}: raise ValueError("Select a native independent list or tag ID field")
        if page_token is not None: raise ValueError("Input page/URL continuation is not declared; bounded initial catalog only")
        if search is not None: _text(search, 100)
        config_type = LinkAceListsConfig if field_name == "list_id" else LinkAceTagsConfig
        result = await cls._dispatch(credential_data, config_type(per_page=context.get("per_page", 20), include_names=context.get("include_names", False)))
        if result.get("status") != "success": raise ValueError(result["error"])
        kind = "List" if field_name == "list_id" else "Tag"
        options = [{"value": str(row["id"]), "label": row.get("name", kind + " " + str(row["id"])), "metadata": {"id": row["id"], "catalog_kind": kind.lower(), "protected_catalog": True, "ownership_proven": False}} for row in result["data"]]
        return {"options": [r for r in options if not search or search.casefold() in r["label"].casefold()], "has_more": result["has_more"], "next_page_token": None}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        raw = self.node_data.get("credentials") if self.node_data.get("credentials") is not None else self.config.credentials
        return await self._dispatch(_credential(raw), self.config.config)
