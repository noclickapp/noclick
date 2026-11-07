"""GoatCounter fixed-origin metadata and aggregated analytics reads.

The supplied token stays bound to a uniquely witnessed site. This native slice
excludes user/token responses, settings, raw events and every write operation.
"""
from __future__ import annotations
import base64
import json
import logging
import math
import re
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, quote_plus, urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-goatcounter"
FAMILIES = ("goatcounter_api_token",)
MAX_BYTES = 4 * 1024 * 1024
MAX_ROWS = 1000
MAX_FILTER_IDS = 200
MAX_DAYS = 31
MAX_DAY_ROWS = 33  # Local count-series bound allowing boundary/timezone days.
SAFE_INTEGER = 9007199254740991
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"

def _token(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 8192 or any(ord(c) <= 32 or ord(c) >= 127 for c in value): raise ValueError("Supply the existing opaque GoatCounter API token, without Bearer prefix")
    return value

def _dns(value):
    if not isinstance(value, str) or len(value) > 253 or not re.fullmatch(LABEL + r"(?:\." + LABEL + r")+", value): raise ValueError("Invalid bare public site hostname")
    if re.fullmatch(r"[0-9.]+", value) or value.endswith((".localhost", ".local", ".internal", ".lan")): raise ValueError("Supply a public DNS site hostname")
    return value

def _origin(value):
    try:
        if not isinstance(value, str) or len(value) > 270: raise ValueError()
        p = urlsplit(value)
        if p.scheme != "https" or p.username is not None or p.password is not None or p.port not in (None, 443) or p.path not in ("", "/") or p.query or p.fragment: raise ValueError()
        host = _dns(p.hostname)
        if host in ("www.goatcounter.com", "goatcounter.com"): raise ValueError()
        return "https://" + host
    except ValueError: raise ValueError("Supply one public HTTPS GoatCounter site origin, no path, IP, credentials, query or alternate port") from None

def _integer(value, minimum=0, maximum=SAFE_INTEGER):
    if type(value) is not int or not minimum <= value <= maximum: raise ValueError("Unverified bounded GoatCounter integer")
    return value

def _form_integer(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,16}", value): value = int(value)
    return _integer(value, 1)

def _text(value, maximum=2048):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value): raise ValueError("Unverified bounded GoatCounter text")
    return value

def _timestamp(value):
    if not isinstance(value, str) or len(value) > 64 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value): raise ValueError("Unverified ISO date-time")
    datetime.fromisoformat(value.replace("Z", "+00:00")); return value

def _hour(value):
    try:
        _timestamp(value); d = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError): raise ValueError("Supply a bounded ISO date-time resolving to a UTC hour") from None
    if d.minute or d.second or d.microsecond: raise ValueError("Start/end must resolve to exact UTC hours")
    return d.isoformat(timespec="seconds").replace("+00:00", "Z")

def _path_ids(value):
    if value is None: return []  # Blank optional form is omission, never name mode.
    if not isinstance(value, list) or len(value) > MAX_FILTER_IDS or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", v) for v in value): raise ValueError("Supply a bounded list of opaque path-ID strings, not names, paths or comma-separated text")
    if len(set(value)) != len(value): raise ValueError("Duplicate GoatCounter path IDs")
    return value

class GoatCounterAPITokenCredential(BaseModel):
    credential_type: Literal["goatcounter_api_token"] = Field("goatcounter_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Existing GoatCounter API Token", json_schema_extra={"ui:widget": "password"})
    site_origin: str = Field(..., title="GoatCounter Site Origin", description="Single public HTTPS site origin, including a documented custom/self-hosted hostname. No API path or credentials in URL.")
    site_id: int = Field(..., ge=1, le=SAFE_INTEGER, title="Selected Site ID", description="Existing exact site ID; current catalog and detail must identify this origin uniquely. Resource access is not actor/account ownership.")
    model_config = ConfigDict(title="GoatCounter API Token", extra="ignore", json_schema_extra={"x-credential-url": "https://www.goatcounter.com/help/api", "x-credential-instructions": "Supply an existing API token and one HTTPS site origin/site ID. Bearer HEADER plus Content-Type application/json, fixed /api/v0 only. The auth guide documents Bearer while Swagger declares basicAuth; this node has no Basic/query/body fallback, token issue or signup. Current code.goatcounter.com/cname are compared internally to the configured hostname; never followed. No /me (it returns token/user), decoded identity, account ownership or permission/entitlement claim."})
    _key = field_validator("api_token")(_token)
    _host = field_validator("site_origin")(_origin)
    _id = field_validator("site_id", mode="before")(_form_integer)

def _op(name, label, category): return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})

class GoatCounterOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

class GoatCounterCheckConfig(GoatCounterOperation):
    operation: Literal["test_connection"] = _op("test_connection", "Check Protected Site Catalog and Origin Witness", "Connection")

class GoatCounterSitesConfig(GoatCounterOperation):
    operation: Literal["list_sites"] = _op("list_sites", "List Accessible Site Metadata", "Sites")
    include_names: bool = Field(False, description="Opt in to code/custom-hostname names; settings, user defaults, link_domain, users and capability fields always omitted.")

class GoatCounterScope(GoatCounterOperation):
    site_id: int = Field(..., ge=1, le=SAFE_INTEGER, title="Selected Site", description="Must equal this current credential's uniquely witnessed site ID; never sent as an analytics query argument.", json_schema_extra={"x-dynamic-options": {"field_name": "site_id", "searchable": True, "allow_custom": True}, "x-resource-type": "goatcounter_site", "x-resource-id-path": "site_id"})
    _site = field_validator("site_id", mode="before")(_form_integer)

class GoatCounterSiteConfig(GoatCounterScope):
    operation: Literal["get_site"] = _op("get_site", "Read Selected Site Metadata", "Sites")
    include_names: bool = Field(False, description="Opt in to site code/custom-hostname names; no settings or account identity.")

class GoatCounterRange(GoatCounterScope):
    start: str = Field(..., description="Explicit ISO date-time resolving to an exact UTC hour. Native range is at most 31 days; no relative/provider defaults.")
    end: str = Field(..., description="Explicit ISO end after start, resolving to an exact UTC hour; normalized UTC on the wire.")
    include_paths: list[str] = Field(default_factory=list, description="Optional opaque path-ID strings from returned path_id values. Never path names; path_by_name=false. Local maximum 200 IDs.", json_schema_extra={"ui:widget": "list"})
    _times = field_validator("start", "end")(_hour)
    _paths = field_validator("include_paths", mode="before")(_path_ids)
    @model_validator(mode="after")
    def bounded_range(self):
        seconds = (datetime.fromisoformat(self.end.replace("Z", "+00:00")) - datetime.fromisoformat(self.start.replace("Z", "+00:00"))).total_seconds()
        if not 3600 <= seconds <= MAX_DAYS * 86400: raise ValueError("GoatCounter range must be 1 hour through 31 days; this is a local bound")
        return self

class GoatCounterTotalsConfig(GoatCounterRange):
    operation: Literal["get_total_counts"] = _op("get_total_counts", "Read Aggregated Visitor Totals", "Analytics")

class GoatCounterHitsConfig(GoatCounterRange):
    operation: Literal["get_hits_counts"] = _op("get_hits_counts", "Read One Page of Path Count Metadata", "Analytics")
    limit: int = Field(20, ge=1, le=100, description="Published limit 1..100/default 20. More is the returned provider flag; no short-page completion guess.")
    exclude_paths: list[str] = Field(default_factory=list, description="Opaque path IDs to exclude for the documented manual pagination contract. No automatic polling/traversal; local maximum 200 IDs.", json_schema_extra={"ui:widget": "list"})
    include_path_details: bool = Field(False, description="Opt in to path names and titles, which may contain user content or identifiers. Referral/client/device/location/raw events always omitted.")
    _limit = field_validator("limit", mode="before")(_form_integer)
    _excluded = field_validator("exclude_paths", mode="before")(_path_ids)
    @model_validator(mode="after")
    def distinct_filters(self):
        if set(self.include_paths) & set(self.exclude_paths): raise ValueError("Include/exclude path IDs must not overlap")
        return self

GoatCounterConfig = Annotated[Union[GoatCounterCheckConfig, GoatCounterSitesConfig, GoatCounterSiteConfig, GoatCounterTotalsConfig, GoatCounterHitsConfig], Field(discriminator="operation")]
class GoatCounterNodeConfig(NodeConfig[GoatCounterConfig, GoatCounterAPITokenCredential]): pass

class GoatCounterMetadata(BaseModel): model_config = ConfigDict(extra="forbid")
class GoatCounterSiteMetadata(GoatCounterMetadata):
    id: int
    parent: Optional[int] = None
    state: Optional[str] = None
    received_data: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    first_hit_at: Optional[str] = None
    code: Optional[str] = None
    cname: Optional[str] = None
class GoatCounterCountDay(GoatCounterMetadata):
    day: str
    daily: int
    hourly: list[int]
    weekly: Optional[int] = None
    monthly: Optional[int] = None
class GoatCounterTotals(GoatCounterMetadata):
    stats: list[GoatCounterCountDay]
    total: int
    total_events: int
    total_utc: int
class GoatCounterHit(GoatCounterMetadata):
    path_id: int
    count: int
    event: bool
    max: int
    stats: list[GoatCounterCountDay]
    path: Optional[str] = None
    title: Optional[str] = None
class GoatCounterHits(GoatCounterMetadata):
    hits: list[GoatCounterHit]
    more: bool
    total: int
    returned_count: int
    next_exclude_paths: Optional[list[str]] = None
    local_filter_bound_reached: bool
    total_semantics: Literal["visitors in the returned result, not global total"] = "visitors in the returned result, not global total"
    one_response_only: Literal[True] = True
    global_completion_verified: Literal[False] = False
class GoatCounterResult(GoatCounterMetadata):
    account_identity_verified: Literal[False] = False
    user_identity_verified: Literal[False] = False
    ownership_verified: Literal[False] = False
    all_permissions_verified: Literal[False] = False
    entitlement_verified: Literal[False] = False
    settings_and_private_fields_omitted: Literal[True] = True
    returned_hosts_followed: Literal[False] = False
    origin_site_witness_verified: Literal[True] = True
    selected_site_id: int
    names_included: bool = False
    path_details_included: bool = False
    results: Optional[list[GoatCounterSiteMetadata]] = None
    sites: Optional[list[GoatCounterSiteMetadata]] = None
    site: Optional[GoatCounterSiteMetadata] = None
    totals: Optional[GoatCounterTotals] = None
    hits: Optional[GoatCounterHits] = None
    catalog_returned_count: Optional[int] = None
    catalog_independent_completion_verified: Optional[Literal[False]] = None
    requested_start: Optional[str] = None
    requested_end: Optional[str] = None
    protected_read_completed: Optional[Literal[True]] = None
    proves: Optional[Literal["reachability"]] = None

class GoatCounterAPIError(ValueError):
    def __init__(self, message, *, authority_rejected=False, http_status=None):
        super().__init__(message); self.authority_rejected = authority_rejected; self.http_status = http_status

async def _request(data, context, route, *, params=None):
    if not re.fullmatch(r"/sites(?:/[1-9][0-9]{0,15})?|/stats/(?:total|hits)", route): raise ValueError("Unsupported GoatCounter native GET route")
    if route.startswith("/sites") and params is not None: raise ValueError("Site metadata routes have no query parameters")
    if route.startswith("/stats"):
        allowed = {"start", "end", "path_by_name", "include_paths"} | ({"limit", "exclude_paths"} if route == "/stats/hits" else set())
        if not isinstance(params, dict) or not {"start", "end", "path_by_name"} <= set(params) or set(params) - allowed or params["path_by_name"] != "false": raise ValueError("Unsupported GoatCounter analytics parameters")
    current = await _stable(data, context); _protect_transport_logs(); privacy = _PRIVATE_REQUEST.set(True)
    try:
        try:
            async with guarded_async_client( timeout=20.0, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", current["site_origin"] + "/api/v0" + route, params=params, headers={"Authorization": "Bearer " + current["api_token"], "Content-Type": "application/json", "Accept": "application/json"}) as response:
                    status = response.status_code
                    if status == 403: raise GoatCounterAPIError("GoatCounter protected read was refused; permission or origin/resource cause remains unverified", http_status=403)
                    if status == 429: raise GoatCounterAPIError("GoatCounter rate limit refused the read; no retry", http_status=429)
                    if status != 200: raise GoatCounterAPIError("GoatCounter returned HTTP" + str(status) + "; protected read is unverified", http_status=status)
                    if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json": raise GoatCounterAPIError("GoatCounter response is not documented JSON")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        chunks.extend(chunk)
                        if len(chunks) > MAX_BYTES: raise GoatCounterAPIError("GoatCounter response exceeds local 4 MiB bound; no truncated success")
                    try: raw = _redact(_parse_json(bytes(chunks).decode("utf-8")), current["api_token"])
                    except (ValueError, TypeError, UnicodeError, RecursionError): raise GoatCounterAPIError("GoatCounter JSON metadata is unverified") from None
        finally: await _stable(data, context)
        if not isinstance(raw, dict) or raw.get("error") is not None or raw.get("errors") is not None or raw.get("status") in ("error", "rejected", "pending_approval", "not_executed", "forbidden"): raise GoatCounterAPIError("GoatCounter did not return a documented successful protected resource")
        return raw
    except GoatCounterAPIError: raise
    except Exception: raise GoatCounterAPIError("GoatCounter transport did not establish a protected read; no replay") from None
    finally: _PRIVATE_REQUEST.reset(privacy)

def _site_metadata(raw, *, expected=None, include_names=False):
    try:
        if not isinstance(raw, dict): raise ValueError()
        item = {"id": _integer(raw.get("id"), 1)}
        if expected is not None and item["id"] != expected: raise ValueError()
        if raw.get("parent") is not None: item["parent"] = _integer(raw["parent"])
        if raw.get("state") is not None: item["state"] = _text(raw["state"], 64)
        if raw.get("received_data") is not None:
            if type(raw["received_data"]) is not bool: raise ValueError()
            item["received_data"] = raw["received_data"]
        for key in ("created_at", "updated_at", "first_hit_at"):
            if raw.get(key) is not None: item[key] = _timestamp(raw[key])
        if include_names:
            for key in ("code", "cname"):
                if raw.get(key) is not None: item[key] = _text(raw[key], 253)
        return GoatCounterSiteMetadata.model_validate(item).model_dump(exclude_none=True)
    except (ValueError, TypeError): raise GoatCounterAPIError("GoatCounter returned another site ID or unverified scalar site metadata") from None

def _observed_hosts(raw):
    hosts = set()
    try:
        if raw.get("code") not in (None, ""):
            code = raw["code"].lower() if isinstance(raw["code"], str) else raw["code"]
            if not isinstance(code, str) or not re.fullmatch(LABEL, code): raise ValueError()
            hosts.add(code + ".goatcounter.com")
        if raw.get("cname") not in (None, ""): hosts.add(_dns(raw["cname"].lower() if isinstance(raw["cname"], str) else raw["cname"]))
        return hosts
    except (ValueError, TypeError): raise GoatCounterAPIError("GoatCounter returned unverified code/cname host witness; no returned host is followed") from None

async def _catalog(data, context, *, include_names=False):
    raw = await _request(data, context, "/sites"); rows = raw.get("sites")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS: raise GoatCounterAPIError("GoatCounter site catalog is not the published bounded sites array")
    parsed = [_site_metadata(row, include_names=include_names) for row in rows]
    if len({row["id"] for row in parsed}) != len(parsed): raise GoatCounterAPIError("GoatCounter catalog repeats a site ID")
    host = urlsplit(data["site_origin"]).hostname
    matched = [row for row in rows if host in _observed_hosts(row)]
    if len(matched) != 1 or matched[0]["id"] != data["site_id"]: raise GoatCounterAPIError("GoatCounter catalog does not uniquely witness the current selected origin/site; empty or ambiguous access is unverified")
    await _stable(data, context)
    return parsed, _site_metadata(matched[0], include_names=include_names)

async def _site_witness(data, context, selected, *, include_names=False):
    if selected != data["site_id"]: raise GoatCounterAPIError("GoatCounter selected site differs from the current credential's origin/site scope")
    await _catalog(data, context)
    raw = await _request(data, context, "/sites/" + str(selected)); item = _site_metadata(raw, expected=selected, include_names=include_names)
    if urlsplit(data["site_origin"]).hostname not in _observed_hosts(raw): raise GoatCounterAPIError("GoatCounter detail no longer matches the current configured origin/site")
    await _stable(data, context); return item

def _days(value):
    try:
        if not isinstance(value, list) or len(value) > MAX_DAY_ROWS: raise ValueError()
        result = []
        for row in value:
            if not isinstance(row, dict) or not isinstance(row.get("day"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["day"]): raise ValueError()
            date.fromisoformat(row["day"]); hours = row.get("hourly")
            if not isinstance(hours, list) or len(hours) > 24: raise ValueError()
            projected = {"day": row["day"], "daily": _integer(row.get("daily")), "hourly": [_integer(v) for v in hours]}
            for key in ("weekly", "monthly"):
                if row.get(key) is not None: projected[key] = _integer(row[key])
            result.append(GoatCounterCountDay.model_validate(projected).model_dump(exclude_none=True))
        if len({r["day"] for r in result}) != len(result): raise ValueError()
        return result
    except (ValueError, TypeError): raise GoatCounterAPIError("GoatCounter daily/hourly aggregate metadata is unverified or exceeds local bounds") from None

def _totals(raw):
    try: return GoatCounterTotals(stats=_days(raw.get("stats")), total=_integer(raw.get("total")), total_events=_integer(raw.get("total_events")), total_utc=_integer(raw.get("total_utc"))).model_dump(exclude_none=True)
    except (ValueError, TypeError): raise GoatCounterAPIError("GoatCounter totals are not the published visitor fields; no inferred count parity") from None

def _hits(raw, cfg):
    try:
        rows = raw.get("hits")
        if not isinstance(rows, list) or len(rows) > cfg.limit or type(raw.get("more")) is not bool: raise ValueError()
        projected = []
        for row in rows:
            if not isinstance(row, dict) or type(row.get("event")) is not bool: raise ValueError()
            pid = _integer(row.get("path_id"), 1); opaque = str(pid)
            if opaque in cfg.exclude_paths or cfg.include_paths and opaque not in cfg.include_paths: raise ValueError()
            item = {"path_id": pid, "count": _integer(row.get("count")), "event": row["event"], "max": _integer(row.get("max")), "stats": _days(row.get("stats"))}
            if cfg.include_path_details:
                for key in ("path", "title"):
                    if row.get(key) is not None: item[key] = _text(row[key])
            projected.append(GoatCounterHit.model_validate(item).model_dump(exclude_none=True))
        if len({row["path_id"] for row in projected}) != len(projected) or raw["more"] and not projected: raise ValueError()
        next_ids = [*cfg.exclude_paths, *[str(row["path_id"]) for row in projected]]
        bound = raw["more"] and len(next_ids) > MAX_FILTER_IDS
        return GoatCounterHits(hits=projected, more=raw["more"], total=_integer(raw.get("total")), returned_count=len(projected), next_exclude_paths=next_ids if raw["more"] and not bound else None, local_filter_bound_reached=bound).model_dump(exclude_none=True)
    except (ValueError, TypeError): raise GoatCounterAPIError("GoatCounter hits/more/returned-result total or path ancestry is unverified") from None

def _analytics_params(cfg):
    params = {"start": cfg.start, "end": cfg.end, "path_by_name": "false"}
    # The complete Swagger2 has no collectionFormat override; its default is CSV.
    if cfg.include_paths: params["include_paths"] = ",".join(cfg.include_paths)
    if cfg.operation == "get_hits_counts":
        params["limit"] = cfg.limit
        if cfg.exclude_paths: params["exclude_paths"] = ",".join(cfg.exclude_paths)
    return params

class GoatCounterNode(WorkflowNode):
    integration_type = "automation-goatcounter"
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="test_connection", noun="GoatCounter protected site catalog and unique configured-origin site", proves="reachability", label_keys=("id",))
    edit_examples = ["Read site IDs/state/timestamps without settings or account identity", "Read bounded visitor totals for explicit UTC hours on the uniquely witnessed origin", "Read one path count page, using returned path IDs for explicit exclude_paths pagination"]
    @classmethod
    def get_config_model(cls): return GoatCounterNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        data = config_data
        _original_family(data); shaped = dict(data)
        if data.get("credentials") is not None: shaped["credentials"] = _shape(data["credentials"])
        try: GoatCounterNodeConfig.model_validate(runtime_config_view(shaped, GoatCounterNodeConfig))
        except ValueError: raise ValueError("GoatCounter native configuration, current site/range scope or credential is invalid") from None
        return super().parse_config(shaped)
    @classmethod
    def validate_config(cls, config_data):
        data = config_data
        try:
            _original_family(data); shaped = dict(data)
            if data.get("credentials") is not None: shaped["credentials"] = _shape(data["credentials"])
            GoatCounterNodeConfig.model_validate(runtime_config_view(shaped, GoatCounterNodeConfig))
        except (ValueError, TypeError): return ValidationResult(valid=False, errors=["GoatCounter native configuration or credential family is invalid"], satisfied_set=None)
        return super().validate_config(shaped)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await _current_data(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
    @classmethod
    async def validate_credential_access(cls, data):
        try:
            current = _shape(data)
            result = await cls._operation(GoatCounterCheckConfig(), current, {})
            if result.get("protected_read_completed") is True:
                return {"valid": True, "proves": "reachability", "account_identity_verified": False}
        except (ValueError, TypeError):
            return {"valid": None, "error": "GoatCounter protected site read could not be verified"}
        return {"valid": None, "error": "GoatCounter protected site read could not be verified"}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, GoatCounterNodeConfig) or self.config.credentials is None: raise ValueError("GoatCounter requires an existing token and fixed origin/site scope")
        node_data = self.node_data or {}; raw = node_data.get("credentials"); data = _shape(raw if isinstance(raw, dict) else self.config.credentials.model_dump())
        context = {"_approval_pool": node_data.get("_approval_pool"), "_credential_id": node_data.get("credential_id"), "_user_id": self.user_id, "_organization_id": self.organization_id, "_workflow_id": self.workflow_id}
        current = await _current_data(data, **_authority(context))
        if node_data.get("credential_id") and not _bound_matches(data, current): raise GoatCounterAPIError("GoatCounter saved-row token/origin/site binding changed before transport", authority_rejected=True)
        result = await self._operation(self.config.config, current, context); await _stable(current, context)
        return {"status": "success", "operation": self.config.config.operation, "data": GoatCounterResult.model_validate({"selected_site_id": current["site_id"], **result}).model_dump(exclude_none=True)}
    @staticmethod
    async def _operation(cfg, data, context):
        if cfg.operation in ("test_connection", "list_sites"):
            rows, selected = await _catalog(data, context, include_names=getattr(cfg, "include_names", False))
            if cfg.operation == "test_connection": return {"results": [selected], "catalog_returned_count": len(rows), "catalog_independent_completion_verified": False, "protected_read_completed": True, "proves": "reachability"}
            return {"sites": rows, "catalog_returned_count": len(rows), "catalog_independent_completion_verified": False, "names_included": cfg.include_names}
        selected = await _site_witness(data, context, cfg.site_id, include_names=getattr(cfg, "include_names", False))
        if cfg.operation == "get_site": return {"site": selected, "names_included": cfg.include_names}
        route = "/stats/total" if cfg.operation == "get_total_counts" else "/stats/hits"
        raw = await _request(data, context, route, params=_analytics_params(cfg))
        return {"totals": _totals(raw), "requested_start": cfg.start, "requested_end": cfg.end} if cfg.operation == "get_total_counts" else {"hits": _hits(raw, cfg), "requested_start": cfg.start, "requested_end": cfg.end, "path_details_included": cfg.include_path_details}
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        if field_name != "site_id": return {"options": [], "next_page_token": None}
        if page_token is not None: raise ValueError("GoatCounter site catalog has no documented continuation")
        if search not in (None, "") and (not isinstance(search, str) or not re.fullmatch(r"[0-9]{1,16}", search)): raise ValueError("GoatCounter site picker searches ID digits only")
        context = _context(credential_data, context or {}); data = await _current_data(credential_data, **_authority(context))
        if context.get("_credential_id") and not _bound_matches(credential_data, data): raise GoatCounterAPIError("GoatCounter picker saved-row token/origin/site binding changed", authority_rejected=True)
        _, selected = await _catalog(data, context); await _stable(data, context); value = str(selected["id"])
        return {"options": [{"value": value, "label": value}] if not search or search in value else [], "next_page_token": None}

def _shape(data):
    if not isinstance(data, dict) or data.get("credential_type", FAMILIES[0]) not in FAMILIES: raise ValueError("GoatCounter credential family is unsupported")
    try: shaped = GoatCounterAPITokenCredential.model_validate({**data, "credential_type": FAMILIES[0]}).model_dump()
    except ValueError: raise ValueError("GoatCounter native credential is invalid") from None
    return {**data, **shaped}

def _binding(data):
    return (data["credential_type"], data["api_token"], data["site_origin"], data["site_id"])

def _bound_matches(bound, current):
    return all(bound.get(key) == current.get(key) for key in ("credential_type", "api_token", "site_origin", "site_id"))

def _original_family(data):
    if not isinstance(data, dict):
        raise ValueError("GoatCounter configuration is invalid")
    creds = data.get("credentials")
    saved = data.get("credential_id") or data.get("credentialIds")
    if saved and not isinstance(creds, dict) or isinstance(creds, dict) and (creds.get("credential_type") is not None or saved) and creds.get("credential_type") not in FAMILIES:
        raise ValueError("GoatCounter saved credential family is missing or unsupported")


@dataclass(frozen=True, repr=False)
class _LookupAuthority:
    pool: Any
    user_id: str
    credential_id: str
    organization_id: Optional[str]
    workflow_id: Optional[str]


async def _current_data(data, *, pool=None, user_id=None, credential_id=None, organization_id=None, workflow_id=None):
    if not credential_id:
        return _shape(data)
    from utils.credentials import resolve_credential_with_owner_fallback
    if pool is None:
        from utils.database_pool import get_native_pool
        pool = get_native_pool()
    if organization_id is None:
        from wss.handlers.workflow_handler import get_user_org_context
        async with pool.acquire() as conn:
            organization_id = await get_user_org_context(conn, user_id)
    result = await resolve_credential_with_owner_fallback(
        credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id,
    )
    if not result or result.get("credential_type") not in FAMILIES:
        raise ValueError("GoatCounter current credential is unavailable or its family is unsupported")
    return {**_shape(result), "_goatcounter_authority": _LookupAuthority(pool, user_id, credential_id, organization_id, workflow_id)}


def _context(data, context):
    result = {k: v for k, v in context.items() if not k.startswith("_")}
    result["_user_id"] = context.get("_user_id")
    bound = data.get("_goatcounter_authority") if isinstance(data, dict) else None
    if type(bound) is _LookupAuthority:
        if bound.user_id != context.get("_user_id"):
            raise ValueError("GoatCounter picker actor does not match saved authority")
        result.update({"_approval_pool": bound.pool, "_user_id": bound.user_id, "_credential_id": bound.credential_id, "_organization_id": bound.organization_id, "_workflow_id": bound.workflow_id})
    return result


def _authority(context):
    return {"pool": context.get("_approval_pool"), "user_id": context.get("_user_id"), "credential_id": context.get("_credential_id"), "organization_id": context.get("_organization_id"), "workflow_id": context.get("_workflow_id")}


def _bounded(value, depth=0):
    if type(value) is int and value.bit_length() > 256:
        raise ValueError("Unverified JSON integer bound")
    if depth > 32 or isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Unverified JSON depth or non-finite number")
    if isinstance(value, dict):
        for key, child in value.items():
            if len(key) > 512:
                raise ValueError("Unverified JSON key")
            _bounded(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_ROWS:
            raise ValueError("Unverified JSON row bound")
        for child in value:
            _bounded(child, depth + 1)


def _redact(value, secret):
    if isinstance(value, str):
        variants = (secret, quote(secret, safe=""), quote_plus(secret, safe=""), base64.b64encode(secret.encode()).decode(), base64.b64encode((secret + ":").encode()).decode())
        for variant in variants:
            pattern = re.sub(r"%([0-9A-Fa-f]{2})", lambda m: '%' + ''.join('[' + c.lower() + c.upper() + ']' for c in m[1]), re.escape(variant))
            value = re.sub(pattern, "[redacted]", value)
        return re.sub(r"(?i)([?&](?:access_token|api_token|api_key|auth_token|token|signature|auth|key)=)[^&#\s]+", r"[redacted]", value)
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


# Narrow reuse of utils.meta_subscriptions._TransportPrivacy: context-local
# masking leaves concurrent unrelated requests untouched and resets on failure.
_PRIVATE_REQUEST = ContextVar("goatcounter_private_request", default=False)


class _TransportPrivacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE_REQUEST.get():
            record.msg, record.args = "GoatCounter private transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_TRANSPORT_PRIVACY = _TransportPrivacy()


def _protect_transport_logs():
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"}
    names.update(name for name in tuple(logging.Logger.manager.loggerDict) if name.startswith(("httpx.", "httpcore.")))
    for name in names:
        logging.getLogger(name).addFilter(_TRANSPORT_PRIVACY)



def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")

def _pairs(items):
    result = {}
    for key, value in items:
        if key in result: raise ValueError("Duplicate JSON field")
        result[key] = value
    return result

def _parse_json(value):
    result = json.loads(value, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    _bounded(result)
    return result

async def _stable(data, context):
    try: current = await _current_data(data, **_authority(context))
    except ValueError: raise GoatCounterAPIError("GoatCounter current credential authority is unavailable or revoked", authority_rejected=True) from None
    if _binding(current) != _binding(data): raise GoatCounterAPIError("GoatCounter current key, owner, version or approval revision changed; result is not accepted", authority_rejected=True)
    return current
