"""Shlink v3 metadata reads with current key, instance and domain witnesses.
Catalog access is reachability only; no redirect URLs, visits or mutating GETs.
"""
import ipaddress
import json
import math
import re
from datetime import datetime
from typing import Annotated, Any, Dict, Literal, Union
from urllib.parse import quote, urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.credentials import resolve_credential_with_owner_fallback
from utils.ssrf import SSRFError, allow_private_hosts, guarded_async_client, normalize_https_origin

MAX_BYTES, MAX_ROWS, MAX_PAGE = 2 * 1024 * 1024, 10000, 10000


def _text(value, limit=255):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value) or re.search(r"(?:https?|ssh|sftp)://", value, re.I): raise ValueError("Use bounded text without controls or URLs")
    return value


def _segment(value):
    value = _text(value)
    if value in {".", ".."} or any(c.isspace() or c in "/\\%?#" for c in value): raise ValueError("Use an exact current single route label; local safety bound")
    return value


def _integer(value):
    if type(value) is not int or not 0 <= value <= 2**53 - 1: raise ValueError("Expected exact nonnegative metadata integer")
    return value


def _object(value):
    if not isinstance(value, dict): raise ValueError("Expected documented Shlink JSON object")
    return value


def _array(value):
    if not isinstance(value, list) or len(value) > MAX_ROWS: raise ValueError("Expected locally bounded documented data array")
    return value


def _date(value):
    if value is None: return None
    value = _text(value, 64)
    try:
        if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None: raise ValueError()
    except ValueError: raise ValueError("Expected raw ISO8601 metadata date") from None
    return value


def _origin(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value): raise ValueError("Use a bounded public HTTPS origin")
    try:
        origin = normalize_https_origin(value, field_name="Shlink instance"); host = urlsplit(origin).hostname
        try: ipaddress.ip_address(host)
        except ValueError: pass
        else: raise ValueError("IP literals are unsupported")
        if not host or "." not in host or host.endswith((".localhost", ".local", ".internal")): raise ValueError()
        return origin
    except (ValueError, SSRFError): raise ValueError("Use one public HTTPS Shlink origin without userinfo, path, query or fragment") from None


class ShlinkAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Shlink API Key", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://shlink.io/documentation/api-docs/authentication/", "x-credential-instructions": "Supply an existing raw API key and one public HTTPS Shlink instance. X-Api-Key header only; fixed /rest/v3. No key issue, refresh, Basic/Bearer or host/version fallback. Catalog access is not actor or instance ownership. Key role coverage, entitlement and parity with software v5.1.7 remain unverified."})
    credential_type: Literal["shlink_api_key"] = Field("shlink_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., repr=False, title="Existing Shlink API Key", json_schema_extra={"ui:widget": "password"})
    instance_url: str = Field(..., title="Public HTTPS Shlink Instance Origin")
    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = _text(value, 4096)
        if any(c.isspace() for c in value): raise ValueError("Supply raw key without prefix or whitespace")
        return clean_secret(value, field_name="Shlink API key")
    @field_validator("instance_url", mode="before")
    @classmethod
    def instance(cls, value): return _origin(value)


def _credential(raw):
    if isinstance(raw, ShlinkAPIKeyCredential): raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("credential_type") != "shlink_api_key": raise ValueError("Select the authoritative Shlink API-key family")
    raw = dict(raw)
    if "token_version" in raw and (type(raw["token_version"]) is not int or raw["token_version"] < 1): raise ValueError("Unsupported saved credential version")
    raw.pop("token_version", None); raw.pop("updated_at", None)
    if set(raw) != {"credential_type", "api_key", "instance_url"}: raise ValueError("Explicit key/public-instance grant required; no other auth family")
    try: return ShlinkAPIKeyCredential.model_validate(raw)
    except Exception: raise ValueError("Shlink supplied key/public-instance binding unsupported") from None


def _stored(raw): return _credential(raw).model_dump(mode="json")


class _CurrentCredential(dict):
    """Recheck staging's authorized credential loader around protected requests."""
    def __init__(self, data, *, pool=None, user_id=None, credential_id=None, organization_id=None, workflow_id=None):
        super().__init__(_stored(data))
        self.pool, self.user_id, self.credential_id = pool, user_id, credential_id
        self.organization_id, self.workflow_id = organization_id, workflow_id
        if credential_id and not user_id:
            raise ValueError("Saved Shlink credentials require an authenticated caller")

    async def reload(self):
        if not self.credential_id:
            return
        raw = await resolve_credential_with_owner_fallback(
            self.credential_id, self.user_id, self.pool,
            org_id=self.organization_id, workflow_id=self.workflow_id,
        )
        if raw is None or _stored(raw) != _stored(self):
            raise ValueError("Shlink saved key or instance changed or is unavailable")

    def __repr__(self): return "<Shlink current credential>"


def _op(value, title): return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Shlink Metadata", "x-is-trigger": False})


class _Names(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    include_names: bool = Field(False, strict=True, title="Include Private Route Labels", description="Opt in to domain, short code, tag and title outputs and custom-domain/code pickers. Redirect URLs remain excluded.")


class ShlinkDomainsConfig(_Names):
    operation: Literal["list_domains"] = _op("list_domains", "Read Accessible Domain Metadata")
    limit: int = Field(10, strict=True, ge=1, le=100, title="Local Output Limit", description="Local prefix bound only. Domains API has no documented input pagination; no paging query is sent and completion remains unknown.")


class _Paged(_Names):
    page: int = Field(1, strict=True, ge=1, le=MAX_PAGE, title="Selected Page", description="Documented first page1; local maximum10000. One selected page only, no blind paging or Link following.")
    items_per_page: int = Field(10, strict=True, ge=1, le=100, title="Items Per Page", description="Local strict integer1..100 bound. Short URL API defaults10; tags API defaults all items, overridden explicitly here. OAS NUMBER has no vendor bounds.")


class ShlinkTagsConfig(_Paged):
    operation: Literal["list_tags"] = _op("list_tags", "Read Accessible Tag Metadata")


class ShlinkShortUrlsConfig(_Paged):
    operation: Literal["list_short_urls"] = _op("list_short_urls", "Read Selected Domain Short URL Metadata")
    domain: str = Field(..., title="Current Domain", description="Explicit selection required. DEFAULT selects the unique current default-domain witness; custom labels must exactly match the current domain catalog.", json_schema_extra={"x-resource-type": "domain", "x-dynamic-options": {"field_name": "domain", "allow_custom": True}})
    @field_validator("domain", mode="before")
    @classmethod
    def selected_domain(cls, value): return _segment(value)


class ShlinkShortUrlConfig(ShlinkShortUrlsConfig):
    operation: Literal["get_short_url"] = _op("get_short_url", "Get Current Short URL Metadata")
    short_code: str = Field(..., title="Current Short Code", description="Must be present on the current selected domain/catalog page. The mutating shorten route is excluded.", json_schema_extra={"x-resource-type": "short_code", "x-dynamic-options": {"field_name": "short_code", "depends_on": "domain", "allow_custom": True, "auto_select_sole_option": False}})
    @field_validator("short_code", mode="before")
    @classmethod
    def selected_code(cls, value):
        value = _segment(value)
        if value == "shorten": raise ValueError("The reserved shorten GET creates a short URL and is excluded")
        return value


ShlinkOperation = Annotated[Union[ShlinkDomainsConfig, ShlinkTagsConfig, ShlinkShortUrlsConfig, ShlinkShortUrlConfig], Field(discriminator="operation")]
class ShlinkNodeConfig(NodeConfig[ShlinkOperation, ShlinkAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _paging(raw, count, exposed, config):
    meta = _object(raw)
    out = {field: _integer(meta[field]) for field in ("currentPage", "pagesCount", "itemsPerPage", "itemsInCurrentPage", "totalItems") if field in meta}
    if "currentPage" in out and out["currentPage"] != config.page: raise ValueError("Returned page differs from selected page")
    if "itemsInCurrentPage" in out and out["itemsInCurrentPage"] != count: raise ValueError("Returned page count differs from actual array")
    if "totalItems" in out and out["totalItems"] < count: raise ValueError("Unsupported filtered count witness")
    truncated = count > config.items_per_page
    more = out["currentPage"] < out["pagesCount"] if {"currentPage", "pagesCount"} <= out.keys() else None
    if truncated: more = None
    return {"pagination": out, "returned_count": count, "exposed_count": exposed, "local_truncated": truncated, "has_more": more, "pagination_complete": None if more is None else not more, "next_page_token": str(config.page + 1) if more is True and config.page < MAX_PAGE else None, "count_scope": "current_key_filtered_collection", "global_coverage_proven": False}


def _short_url(raw, expected_domain, names):
    row = _object(raw)
    if "domain" not in row or row["domain"] != expected_domain: raise ValueError("Explicit returned domain differs from current selected domain")
    code = _segment(row.get("shortCode"))
    if code == "shorten": raise ValueError("Reserved mutating route excluded")
    visits, meta = _object(row.get("visitsSummary")), _object(row.get("meta"))
    if any(f not in meta for f in ("validSince", "validUntil", "maxVisits")) or row.get("dateCreated") is None: raise ValueError("Explicit documented dates and nullable metadata required")
    maximum = meta["maxVisits"]
    if maximum is not None and (type(maximum) not in {int, float} or not math.isfinite(maximum) or abs(maximum) > 2**53 - 1): raise ValueError("Expected nullable finite metadata NUMBER; no integer coercion")
    out = {"dateCreated": _date(row["dateCreated"]), "visitsSummary": {f: _integer(visits.get(f)) for f in ("total", "nonBots", "bots")}, "meta": {"validSince": _date(meta["validSince"]), "validUntil": _date(meta["validUntil"]), "maxVisits": maximum}}
    for f in ("crawlable", "forwardQuery", "hasRedirectRules"):
        if type(row.get(f)) is not bool: raise ValueError("Expected documented short URL flag")
        out[f] = row[f]
    if names:
        if "title" not in row: raise ValueError("Explicit nullable title required")
        tags = [_text(t) for t in _array(row.get("tags"))]
        out.update(shortCode=code, domain=expected_domain, title=None if row["title"] is None else _text(row["title"], 1024), tags=tags)
    return out, (expected_domain, code)


class _ProviderError(Exception):
    def __init__(self, result): self.result = result


class _Session:
    def __init__(self, raw, config): self.raw, self.key, self.config, self.attempted, self.status = raw, _credential(raw), config, False, None
    def error(self, message): return {"status": "error", "action": self.config.operation, "error": message, "executed": self.attempted, "mutation_attempted": False, "_halt_downstream": True, **({"http_status": self.status} if self.status is not None else {})}
    async def request(self, route, domain=None, code=None):
        if route not in {"domains", "tags", "short-urls"}: raise ValueError("Closed Shlink metadata route required")
        path, params = "/rest/v3/" + route, {}
        if route in {"tags", "short-urls"} and code is None: params = {"page": str(self.config.page), "itemsPerPage": str(self.config.items_per_page)}
        if route == "short-urls":
            if code is not None:
                if code == "shorten": raise ValueError("Mutating shorten route excluded")
                path += "/" + quote(_segment(code), safe="")
                if domain != "DEFAULT": params["domain"] = _segment(domain)
            else: params["domain"] = _segment(domain)
        try:
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            key = _credential(self.raw); self.status = None
            if allow_private_hosts(): raise ValueError("Shlink requires public-only outbound transport")
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                async with client.stream("GET", key.instance_url + path, params=params, headers={"X-Api-Key": key.api_key, "Accept": "application/json"}) as response:
                    self.status = response.status_code; headers = response.headers; body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_BYTES: raise ValueError("Shlink response exceeds local byte bound")
                        body.extend(chunk)
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            if self.status != 200:
                reason = {401: "Key authentication failed; invalid, disabled or expired is ambiguous", 403: "Permission is unverified", 404: "Resource is missing-or-invisible", 429: "Rate limit prevents verification"}.get(self.status, "Protected metadata access could not be verified")
                raise _ProviderError(self.error(reason + "; private provider bodies omitted; no retry or fallback"))
            if "application/json" not in headers.get("content-type", "").lower(): raise ValueError("Expected Shlink JSON representation")
            return _object(json.loads(body))
        except (httpx.HTTPError, SSRFError): raise _ProviderError(self.error("Shlink transport outcome unknown; no retry or fallback")) from None
    async def domains(self, limit=100):
        raw = await self.request("domains"); envelope = _object(raw.get("domains")); rows = _array(envelope.get("data")); anchors = []
        for row in rows:
            row = _object(row)
            if type(row.get("isDefault")) is not bool: raise ValueError("Expected current domain default flag")
            anchors.append((_segment(row.get("domain")), row["isDefault"]))
        if len({a[0] for a in anchors}) != len(anchors): raise ValueError("Ambiguous current domain catalog")
        out = [{"isDefault": default, **({"domain": name} if self.config.include_names else {})} for name, default in anchors[:limit]]
        return {"data": out, "returned_count": len(rows), "exposed_count": len(out), "local_truncated": len(rows) > limit, "has_more": None, "pagination_complete": None, "next_page_token": None, "default_domain_available": sum(a[1] for a in anchors) == 1, "count_scope": "current_key_filtered_collection", "global_coverage_proven": False}, anchors
    async def parent(self):
        _, anchors = await self.domains()
        if self.config.domain == "DEFAULT":
            defaults = [a for a in anchors if a[1]]
            if len(defaults) != 1: raise ValueError("Exactly one current default-domain witness required")
            return defaults[0], None
        anchor = next((a for a in anchors if a[0] == self.config.domain), None)
        if anchor is None: raise ValueError("Custom domain not in current key-filtered domain catalog")
        return anchor, self.config.domain
    async def short_urls(self, expected):
        raw = await self.request("short-urls", self.config.domain); envelope = _object(raw.get("shortUrls")); rows = _array(envelope.get("data"))
        parsed = [_short_url(row, expected, self.config.include_names) for row in rows[:self.config.items_per_page]]; anchors = [a for _, a in parsed]
        if len(set(anchors)) != len(anchors): raise ValueError("Ambiguous current short URL catalog")
        data = [r for r, _ in parsed]
        return {"data": data, **_paging(envelope.get("pagination", {}), len(rows), len(data), self.config)}, anchors


class ShlinkNode(WorkflowNode):
    integration_type = "automation-shlink"
    connection_evidence = ConnectionEvidence(operation="list_domains", noun="Shlink protected domain catalog", proves="reachability")
    edit_examples = ["Read current short URL validity and aggregate visit counts without redirect URLs", "Read key-filtered domain and tag metadata without exposing private route labels"]
    @classmethod
    def get_config_model(cls): return ShlinkNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: _stored(config_data["credentials"])
            except ValueError as error: raise ConfigValidationError(str(error)) from None
        return super().parse_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Staging resolves access with the workflow/organization context before
        # this hook. Static API keys do not rotate; do not resolve them again
        # through a hook that cannot receive that context.
        return _stored(credential_data)
    @classmethod
    async def validate_credential_access(cls, credential_data):
        from dataclasses import asdict
        from nodes.core.connection_evidence import collect_evidence
        evidence = await collect_evidence(node_type=cls.integration_type, user_id="", credential_data=_stored(credential_data))
        return {"valid": evidence.reachable, "evidence": asdict(evidence)}
    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config)
        try:
            if config.operation == "list_domains":
                out, anchors = await session.domains(config.limit)
                if set((await session.domains(config.limit))[1]) != set(anchors): raise ValueError("Current domain catalog changed")
            elif config.operation == "list_tags":
                envelope = _object((await session.request("tags")).get("tags")); rows = [_text(t) for t in _array(envelope.get("data"))]
                if len(set(rows)) != len(rows): raise ValueError("Ambiguous current tag catalog")
                exposed = min(len(rows), config.items_per_page); out = {"data": rows[:exposed] if config.include_names else [], **_paging(envelope.get("pagination", {}), len(rows), exposed if config.include_names else 0, config)}
            elif config.operation in {"list_short_urls", "get_short_url"}:
                parent, expected = await session.parent(); out, anchors = await session.short_urls(expected)
                if config.operation == "get_short_url":
                    selected = (expected, config.short_code)
                    if selected not in anchors: raise ValueError("Short code not on current selected page; no global absence assertion")
                    data, anchor = _short_url(await session.request("short-urls", config.domain, config.short_code), expected, config.include_names)
                    if anchor != selected: raise ValueError("Detail differs from exact current domain/short-code witness")
                    out = {"data": data}
                    if selected not in (await session.short_urls(expected))[1]: raise ValueError("Short code left current selected page")
                if (await session.parent())[0] != parent: raise ValueError("Current selected domain/default witness changed")
            else: raise ValueError("Closed native operation required")
            if session.key.api_key in json.dumps(out, ensure_ascii=False, allow_nan=False): raise ValueError("Output contains credential material")
            return {"status": "success", "action": config.operation, "executed": True, "http_status": session.status, "mutation_attempted": False, "snapshot_stable": False, "protected_reachability_verified": True, "principal_identity_proven": False, "instance_ownership_proven": False, **out}
        except _ProviderError as error: return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError): return session.error("Current saved credential/domain ancestry or typed metadata could not be established; no raw fallback/retry")
    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        _credential(credential_data); context = context or {}
        if field_name not in {"domain", "short_code"}: raise ValueError("Select a native domain or short-code field")
        if search is not None: _text(search, 100)
        if field_name == "domain":
            if page_token is not None: raise ValueError("Domain API has no documented paging inputs")
            result = await cls._dispatch(credential_data, ShlinkDomainsConfig(include_names=context.get("include_names", False), limit=100))
            if result.get("status") != "success": raise ValueError(result["error"])
            options = [{"value": "DEFAULT", "label": "Current Default Domain", "metadata": {"protected_catalog": True, "ownership_proven": False}}] if result["default_domain_available"] else []
            options.extend({"value": r["domain"], "label": r["domain"], "metadata": {"protected_catalog": True, "ownership_proven": False}} for r in result["data"] if "domain" in r and not r["isDefault"])
            return {"options": [r for r in options if not search or search.casefold() in r["label"].casefold()], "has_more": None, "next_page_token": None}
        if context.get("include_names") is not True: return {"options": [], "has_more": None, "next_page_token": None, "message": "Enable Include Private Route Labels for short-code choices, or enter a known current code"}
        if "domain" not in context: raise ValueError("Explicit current domain context required for short-code options")
        page = context.get("page", 1)
        if page_token is not None:
            if not isinstance(page_token, str) or not re.fullmatch(r"[1-9][0-9]{0,4}", page_token) or int(page_token) > MAX_PAGE: raise ValueError("Use only bounded numeric continuation")
            page = int(page_token)
        config = ShlinkShortUrlsConfig(domain=context["domain"], page=page, items_per_page=context.get("items_per_page", 10), include_names=True)
        result = await cls._dispatch(credential_data, config)
        if result.get("status") != "success": raise ValueError(result["error"])
        options = [{"value": r["shortCode"], "label": r["shortCode"], "metadata": {"domain": config.domain, "protected_catalog": True, "ownership_proven": False}} for r in result["data"]]
        return {"options": [r for r in options if not search or search.casefold() in r["label"].casefold()], "has_more": result["has_more"], "next_page_token": result["next_page_token"]}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        raw = self.node_data.get("credentials") if self.node_data.get("credentials") is not None else self.config.credentials
        initial = _credential(raw)
        credential = _CurrentCredential(initial.model_dump(mode="json"), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data["credential_id"], workflow_id=self.workflow_id, organization_id=self.organization_id) if self.node_data.get("credential_id") else initial
        if isinstance(credential, _CurrentCredential): await credential.reload()
        return await self._dispatch(credential, self.config.config)
