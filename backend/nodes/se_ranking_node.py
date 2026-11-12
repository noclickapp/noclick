"""SE Ranking's current Project API, with explicit project and account bounds."""
import asyncio
import base64
from contextvars import ContextVar
from datetime import date
import hashlib
import hmac
import json
import logging
import math
import re
import time
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from opentelemetry import propagate
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import normalize_search
from utils.outbound_trace_privacy import OutboundTraceProvider
from utils.ssrf import assert_exact_url_origin, guarded_async_client

ORIGIN, PREFIX = "https://api.seranking.com", "/v1/project-management"
FAMILIES = {"se_ranking_api_token"}
PRIVATE_REQUEST = ContextVar("se_ranking_private_http_request", default=False)


class _RequestFilter(logging.Filter):
    def filter(self, record):
        if not PRIVATE_REQUEST.get():
            return True
        record.msg, record.args = "SE Ranking HTTP transport activity", ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _RequestFilter()


def _install_privacy():
    names = {"httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"}
    names.update(n for n in tuple(logging.Logger.manager.loggerDict) if n.startswith(("httpx.", "httpcore.")))
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)


def _id(value):
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,15}", value):
        value = int(value)
    if type(value) is not int or not 1 <= value <= 9007199254740991:
        raise ValueError("Enter a positive SE Ranking resource ID")
    return value


def _text(value, limit=255):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("SE Ranking metadata text is invalid")
    return value


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Use a SE Ranking date in YYYY-MM-DD format")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("SE Ranking date is invalid") from None
    return value


Identifier = Annotated[int, BeforeValidator(_id)]
Day = Annotated[str, BeforeValidator(_date)]


def _family(raw):
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    if not isinstance(raw, dict) or ("credential_type" in raw and (not isinstance(raw["credential_type"], str) or raw["credential_type"] not in FAMILIES)):
        raise ValueError("Connect a native SE Ranking API token credential")
    return raw


class SERankingApiTokenCredential(BaseModel):
    credential_type: Literal["se_ranking_api_token"] = Field("se_ranking_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=8192, title="SE Ranking API Token", description="Supplied current Project API key sent as Authorization: Token, never a query parameter. Eligibility is not assumed.", json_schema_extra={"ui:widget": "password"})
    expected_email: str = Field(..., min_length=3, max_length=254, title="Expected Account Email", description="Must exactly match the protected current /users/me profile. No numeric account ID or project ownership is inferred.")
    project_ids: list[Identifier] = Field(..., min_length=1, max_length=20, title="Allowed Project IDs", description="Explicit project boundary; API access and exact project membership are checked for each operation.", json_schema_extra={"x-resource-type": "se_ranking_project"})
    model_config = ConfigDict(title="SE Ranking API Token", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://seranking.com/api/project/getting-started/"})

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply a valid SE Ranking API token")
        return value

    @field_validator("expected_email")
    @classmethod
    def email(cls, value):
        _text(value, 254)
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter the actual SE Ranking account email")
        return value

    @field_validator("project_ids")
    @classmethod
    def distinct(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("SE Ranking project IDs must be distinct")
        return value


# SE Ranking's own MCP server: agents get its tools through a person's SE Ranking sign-in.
SeRankingMcpCredential = mcp_credential("se_ranking", "https://api.seranking.com/mcp", app="SE Ranking")
SERankingCredential = Union[SERankingApiTokenCredential, SeRankingMcpCredential]


def _credential(raw):
    raw = _family(raw)
    try:
        return SERankingApiTokenCredential.model_validate(raw)
    except Exception:
        raise ValueError("SE Ranking credential is invalid; reconnect") from None


def _op(value, title, group):
    return Field(value, title=title, json_schema_extra={"x-operation-group": group})


def _selector(title, field, resource, parent=None):
    options = {"field_name": field, "searchable": True, "allow_custom": True}
    if parent:
        options["depends_on"] = parent
    return Field(..., title=title, json_schema_extra={"x-resource-type": "se_ranking_" + resource, "x-dynamic-options": options})


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetProfile(Settings):
    operation: Literal["get_profile"] = _op("get_profile", "Get Protected Current Profile", "Connection")


class Page(Settings):
    page_size: int = Field(25, ge=1, le=100, title="Page Size")
    page_token: Optional[str] = Field(None, max_length=18000, title="Continuation", json_schema_extra={"ui:hidden": True})


class ListProjects(Page):
    operation: Literal["list_projects"] = _op("list_projects", "List Allowed Project Metadata", "Projects")


class Project(Settings):
    site_id: Identifier = _selector("Project", "site_id", "project")


class GetProject(Project):
    operation: Literal["get_project"] = _op("get_project", "Get Selected Project Metadata", "Projects")


class ListSearchEngines(Page, Project):
    operation: Literal["list_search_engines"] = _op("list_search_engines", "List Project Search Engine Configurations", "Projects")


class Engine(Project):
    site_engine_id: Identifier = _selector("Project Search Engine", "site_engine_id", "engine", "site_id")


class ListKeywords(Page, Engine):
    operation: Literal["list_keywords"] = _op("list_keywords", "List Project Keywords with Engine Check Dates", "Keywords")


class GetSummary(Project):
    operation: Literal["get_project_summary"] = _op("get_project_summary", "Get Project Summary Metrics", "Projects")


class GetKeywordPositions(Engine):
    operation: Literal["get_keyword_positions"] = _op("get_keyword_positions", "Get Selected Keyword Ranking History", "Rankings")
    keyword_id: Identifier = _selector("Keyword", "keyword_id", "keyword", "site_engine_id")
    date_from: Day = Field(..., title="Start Date")
    date_to: Day = Field(..., title="End Date")

    @model_validator(mode="after")
    def dates(self):
        if not 0 <= (date.fromisoformat(self.date_to) - date.fromisoformat(self.date_from)).days <= 30:
            raise ValueError("Select an ordered ranking period of at most 31 days")
        return self


class GetHistoricalDates(Engine):
    operation: Literal["get_historical_dates"] = _op("get_historical_dates", "Get Project Engine Historical Checkpoints", "Rankings")


class ListKeywordGroups(Page, Project):
    operation: Literal["list_keyword_groups"] = _op("list_keyword_groups", "List Project Keyword Groups", "Keyword Groups")


class CreateKeywordGroup(Project):
    operation: Literal["create_keyword_group"] = _op("create_keyword_group", "Create Keyword Group Metadata", "Keyword Groups")
    name: str = Field(..., min_length=1, max_length=255, title="New Group Name")
    confirm_create: Literal[True] = Field(..., title="Confirm Keyword Group Creation", description="Creates metadata in the selected accessible project. No keywords are added or moved and no rank check is started.")

    @field_validator("name")
    @classmethod
    def name_text(cls, value):
        return _text(value)


class DeleteKeywordGroup(Project):
    operation: Literal["delete_keyword_group"] = _op("delete_keyword_group", "Delete Empty Keyword Group Metadata", "Keyword Groups")
    group_id: Identifier = _selector("Keyword Group", "group_id", "group", "site_id")
    confirm_delete: Literal[True] = Field(..., title="Confirm Empty Group Deletion", description="Requires the group to belong to this project and have no keywords. Verifies HTTP 204 and independent list absence; no keyword delete or move is issued.")


class ListCompetitors(Page, Project):
    operation: Literal["list_competitors"] = _op("list_competitors", "List Project Competitor Metadata", "Competitors")


class ListAudits(Page, Project):
    operation: Literal["list_audits"] = _op("list_audits", "List Existing Project Audit Metadata", "Existing Audits")


class GetAuditStatus(Project):
    operation: Literal["get_audit_status"] = _op("get_audit_status", "Read Existing Project Audit Status", "Existing Audits")
    audit_id: Identifier = _selector("Existing Project Audit", "audit_id", "audit", "site_id")


Operations = Annotated[Union[GetProfile, ListProjects, GetProject, ListSearchEngines, ListKeywords,
    GetSummary, GetKeywordPositions, GetHistoricalDates, ListKeywordGroups, CreateKeywordGroup,
    DeleteKeywordGroup, ListCompetitors, ListAudits, GetAuditStatus], Field(discriminator="operation")]


class SERankingNodeConfig(NodeConfig[Operations, SERankingCredential]):
    pass


class _Authority:
    """Per-call token context; saved credential admission belongs to shared loaders."""
    def __init__(self, credential):
        self.credential = _credential(credential)

    async def check(self):
        _credential(self.credential)

    def key(self):
        return hashlib.sha256(json.dumps(self.credential.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


def _public(value, credential):
    key = credential.api_token
    canaries = {key, quote(key, safe=""), base64.b64encode(key.encode()).decode(), base64.urlsafe_b64encode(key.encode()).decode(), key.encode().hex()}
    if any(s in json.dumps(value, ensure_ascii=False) for s in canaries):
        raise ValueError("SE Ranking response contained protected credential data")
    return value


def _number(value, minimum=None):
    if type(value) not in {int, float} or not math.isfinite(value) or minimum is not None and value < minimum:
        raise ValueError("SE Ranking metric is invalid")
    return value


def _project(kind, row, credential):
    if not isinstance(row, dict):
        raise ValueError("SE Ranking resource is malformed")
    result = {"id": _id(row.get("site_engine_id") if kind == "engine" else row.get("id"))}
    for key in ({"project": ("title", "name"), "engine": ("region_name", "lang_code"), "keyword": ("name", "first_check_date"), "group": ("name", "creation_date"), "competitor": ("name",), "audit": ("title", "status", "last_update")}[kind]):
        if row.get(key) is not None:
            result[key] = _text(row[key], 1024)
    numeric = {"project": ("group_id", "is_active", "keyword_count"), "engine": ("search_engine_id", "region_id", "keyword_count"), "keyword": (), "group": (), "competitor": ("domain_trust",), "audit": ()}[kind]
    for key in numeric:
        if row.get(key) is not None:
            if type(row[key]) is not int or row[key] < 0:
                raise ValueError("SE Ranking integer metadata is invalid")
            result[key] = row[key]
    if kind == "keyword":
        group = row.get("group_id")
        if group is not None:
            if type(group) is not str or not re.fullmatch(r"[0-9]{1,16}", group):
                raise ValueError("SE Ranking keyword group reference is invalid")
            result["group_id"] = int(group)
        if "site_engine_ids" in row:
            engines = row["site_engine_ids"]
            if not isinstance(engines, list) or len(engines) > 100:
                raise ValueError("SE Ranking keyword engine references are malformed")
            result["site_engine_ids"] = [_id(engine) for engine in engines]
    # guest_link, links, business phone, avatar, audit errors/config and owner IDs
    # are intentionally omitted from every resource projection.
    return _public(result, credential)


class SERankingRequestError(ValueError):
    def __init__(self, message, *, status=None, outcome="unverified"):
        super().__init__(message)
        self.status, self.outcome = status, outcome


class _Client:
    def __init__(self, authority):
        self.authority, self.credential = authority, authority.credential
        self.verified, self.projects_cache, self.last_request = False, None, 0

    def site(self, value):
        if _id(value) not in self.credential.project_ids:
            raise ValueError("Select a project allowed by this SE Ranking connection")
        return value

    async def _http(self, method, path, *, params=None, body=None):
        reads = {"/users/me", "/sites", "/sites/search-engines", "/keywords", "/sites/summary", "/sites/positions", "/sites/positions/checkpoints", "/keywords/groups", "/competitors", "/audits", "/audits/status"}
        create = method == "POST" and path == "/keywords/groups"
        delete = method == "DELETE" and path == "/keywords/groups"
        if not (method == "GET" and path in reads or create or delete):
            raise ValueError("Unsupported SE Ranking native route")
        params = params or {}
        expected = {"/users/me": set(), "/sites": set(), "/sites/search-engines": {"site_id"}, "/keywords": {"site_id"}, "/sites/summary": {"site_id"}, "/sites/positions": {"site_id", "site_engine_id", "date_from", "date_to"}, "/sites/positions/checkpoints": {"site_id", "site_engine_id"}, "/keywords/groups": {"site_id"}, "/competitors": {"site_id"}, "/audits": {"limit", "offset"}, "/audits/status": {"audit_id"}}[path]
        if path == "/keywords" and "site_engine_id" in params:
            expected = {"site_id", "site_engine_id"}
        if create:
            expected = set()
            if not isinstance(body, dict) or set(body) != {"site_id", "name"}:
                raise ValueError("SE Ranking supports only typed keyword-group creation")
            self.site(body["site_id"])
            _text(body["name"])
        elif delete:
            expected = {"group_id"}
            if body is not None:
                raise ValueError("SE Ranking group deletion cannot carry other changes")
        elif body is not None:
            raise ValueError("SE Ranking reads cannot carry write payloads")
        if not isinstance(params, dict) or set(params) != expected:
            raise ValueError("Unsupported SE Ranking native query")
        for key in {"site_id", "site_engine_id", "group_id", "audit_id"} & set(params):
            _id(params[key])
        if "site_id" in params:
            self.site(params["site_id"])
        if path == "/audits" and (type(params["limit"]) is not int or not 1 <= params["limit"] <= 100 or type(params["offset"]) is not int or not 0 <= params["offset"] < 10000):
            raise ValueError("SE Ranking audit paging is invalid")
        if path == "/sites/positions":
            if not 0 <= (date.fromisoformat(_date(params["date_to"])) - date.fromisoformat(_date(params["date_from"]))).days <= 30:
                raise ValueError("SE Ranking ranking period exceeds its bound")
        url = ORIGIN + PREFIX + path
        assert_exact_url_origin(url, ORIGIN)
        await self.authority.check()
        delay = .22 - (time.monotonic() - self.last_request)
        if delay > 0:
            await asyncio.sleep(delay)
        self.last_request = time.monotonic()
        headers = {"Authorization": "Token " + self.credential.api_token, "Accept": "application/json", "Content-Type": "application/json"}
        _install_privacy()
        private = PRIVATE_REQUEST.set(True)
        try:
            with OutboundTraceProvider().get_tracer(__name__).start_as_current_span(method, kind=SpanKind.CLIENT,
                attributes={"http.request.method": method, "url.full": ORIGIN + "/[native-resource]", "url.scheme": "https", "server.address": "api.seranking.com", "server.port": 443}, record_exception=False, set_status_on_exception=False) as span:
                try:
                    propagate.inject(headers)
                    with suppress_http_instrumentation():
                        async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=httpx.Timeout(20)) as client:
                            async with client.stream(method, url, headers=headers, params=params, json=_public(body, self.credential) if body is not None else None) as response:
                                status, media = response.status_code, response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                                span.set_attribute("http.response.status_code", status)
                                content = bytearray()
                                # A documented 204 is bodyless; do not parse it.
                                if status != 204:
                                    async for chunk in response.aiter_bytes():
                                        if len(content) + len(chunk) > 2_000_000:
                                            raise SERankingRequestError("SE Ranking response exceeds its bound; verify any write")
                                        content.extend(chunk)
                except BaseException as error:
                    span.set_status(StatusCode.ERROR)
                    if isinstance(error, httpx.HTTPError):
                        raise SERankingRequestError("SE Ranking metadata change outcome is unknown; verify before retrying" if method != "GET" else "SE Ranking request could not be read; access is unverified") from None
                    raise
        finally:
            PRIVATE_REQUEST.reset(private)
        await self.authority.check()
        expected_status = 201 if create else 204 if delete else 200
        if status != expected_status:
            outcome = "unauthenticated" if status == 401 else "forbidden" if status == 403 else "rate_limited" if status == 429 else "unverified"
            raise SERankingRequestError(f"SE Ranking returned HTTP {status}; check access and verify any uncertain change", status=status, outcome=outcome)
        if status == 204:
            return None
        try:
            if media != "application/json":
                raise ValueError
            value = json.loads(content)
            if not isinstance(value, (dict, list)) or isinstance(value, dict) and (value.get("error") or value.get("message")):
                raise ValueError
            return value
        except Exception:
            raise SERankingRequestError("SE Ranking response is not documented JSON; verify any change before retrying", status=status) from None

    async def profile(self):
        row = await self._http("GET", "/users/me")
        if not isinstance(row, dict) or row.get("email") != self.credential.expected_email or type(row.get("email_verified")) is not bool:
            raise ValueError("SE Ranking protected current account differs")
        result = {"email": row["email"], "email_verified": row["email_verified"], "principal_kind": "account_email", "project_ownership_verified": False}
        for key in ("first_name", "last_name", "lang"):
            if row.get(key):
                result[key] = _text(row[key], 255)
        self.verified = True
        return _public(result, self.credential)

    async def collection(self, kind, site=None, engine=None):
        if not self.verified:
            raise ValueError("SE Ranking protected account evidence is required")
        path = {"project": "/sites", "engine": "/sites/search-engines", "keyword": "/keywords", "group": "/keywords/groups", "competitor": "/competitors"}[kind]
        params = {} if kind == "project" else {"site_id": self.site(site)}
        if engine is not None:
            params["site_engine_id"] = _id(engine)
        rows = await self._http("GET", path, params=params)
        if not isinstance(rows, list) or len(rows) > 5000:
            raise ValueError("SE Ranking collection is not a bounded documented array")
        projected = [_project(kind, row, self.credential) for row in rows]
        if len({row["id"] for row in projected}) != len(projected):
            raise ValueError("SE Ranking resource IDs repeat")
        if kind == "project":
            projected = [row for row in projected if row["id"] in self.credential.project_ids]
            self.projects_cache = projected
        return projected

    async def project(self, site):
        self.site(site)
        rows = self.projects_cache if self.projects_cache is not None else await self.collection("project")
        matches = [row for row in rows if row["id"] == site]
        if len(matches) != 1:
            raise ValueError("SE Ranking selected project is not currently accessible")
        return matches[0]

    async def engine(self, site, engine):
        rows = await self.collection("engine", site)
        if _id(engine) not in {row["id"] for row in rows}:
            raise ValueError("SE Ranking search engine belongs to another project")

    def seal(self, value):
        blob = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(blob).decode().rstrip("=") + "." + hmac.new(self.authority.key().encode(), blob, hashlib.sha256).hexdigest()

    def unseal(self, token):
        try:
            encoded, signature = token.split(".")
            blob = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
            if not hmac.compare_digest(signature, hmac.new(self.authority.key().encode(), blob, hashlib.sha256).hexdigest()):
                raise ValueError
            value = json.loads(blob)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except Exception:
            raise ValueError("SE Ranking continuation belongs to another or changed authority") from None

    def local_page(self, rows, cfg, kind, engine=None):
        rows = sorted(rows, key=lambda row: row["id"])
        scope = hashlib.sha256(json.dumps([kind, getattr(cfg, "site_id", None), engine, cfg.page_size, rows], sort_keys=True).encode()).hexdigest()
        offset = 0
        if cfg.page_token:
            token = self.unseal(cfg.page_token)
            if set(token) != {"scope", "offset"} or token["scope"] != scope or type(token["offset"]) is not int or not 0 < token["offset"] < len(rows) or token["offset"] % cfg.page_size:
                raise ValueError("SE Ranking collection continuation changed or is invalid")
            offset = token["offset"]
        end = offset + cfg.page_size
        return {"data": rows[offset:end], "total": len(rows), "next_page_token": self.seal({"scope": scope, "offset": end}) if end < len(rows) else None, "pagination_kind": "local_complete_array", "http_status": 200}

    async def audit_page(self, site, size, token=None):
        scope = hashlib.sha256(json.dumps([site, size]).encode()).hexdigest()
        offset, seen = 0, []
        if token:
            value = self.unseal(token)
            if set(value) != {"kind", "scope", "offset", "seen"} or value["kind"] != "audits" or value["scope"] != scope or type(value["offset"]) is not int or not 0 < value["offset"] < 10000 or value["offset"] % size or not isinstance(value["seen"], list) or len(value["seen"]) != value["offset"] // size or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in value["seen"]):
                raise ValueError("SE Ranking audit continuation is invalid")
            offset, seen = value["offset"], value["seen"]
        value = await self._http("GET", "/audits", params={"limit": size, "offset": offset})
        rows = value.get("items") if isinstance(value, dict) else None
        total = value.get("total") if isinstance(value, dict) else None
        if not isinstance(rows, list) or len(rows) > size or type(total) is not int or not 0 <= total <= 10000 or offset + len(rows) > total:
            raise ValueError("SE Ranking audit page is malformed or exceeds its bound")
        ids = [_id(row.get("id")) if isinstance(row, dict) else None for row in rows]
        fingerprint = hashlib.sha256(json.dumps(ids).encode()).hexdigest()
        more = offset + len(rows) < total
        if None in ids or len(set(ids)) != len(ids) or rows and fingerprint in seen or more and (len(rows) != size or offset + size >= 10000):
            raise ValueError("SE Ranking audit page repeated or changed")
        selected = []
        for row in rows:
            if row.get("has_project") is True and row.get("site_id") == site and type(row.get("site_id")) is int:
                selected.append({**_project("audit", row, self.credential), "site_id": site})
        return {"data": selected, "total": None, "next_page_token": self.seal({"kind": "audits", "scope": scope, "offset": offset + size, "seen": seen + [fingerprint]}) if more else None, "http_status": 200}

    async def audit_witness(self, site, audit):
        token = None
        for _ in range(20):
            page = await self.audit_page(site, 50, token)
            if audit in {row["id"] for row in page["data"]}:
                return
            token = page["next_page_token"]
            if not token:
                break
        raise ValueError("SE Ranking audit lacks a current selected-project witness within the bounded scan")


class SERankingNode(WorkflowNode):
    integration_type = "automation-se-ranking"
    credential_provider_labels = {"se_ranking": "SE Ranking Account"}
    connection_evidence = ConnectionEvidence(noun="SE Ranking account", operation="get_profile", identity_operation="get_profile", identity_keys=("email",), proves="account")

    @classmethod
    def get_config_model(cls):
        return SERankingNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if raw is not None:
            _family(raw)
        try:
            data = runtime_config_view(config_data, SERankingNodeConfig)
            TypeAdapter(Operations).validate_python(data["config"])
            if raw is not None:
                data["credentials"] = _credential(raw).model_dump()
        except Exception:
            raise ValueError("SE Ranking configuration is invalid; check typed operation fields") from None
        return super().parse_config(data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if config_data.get("credentials") is not None:
                _credential(config_data["credentials"])
            return super().validate_config(config_data)
        except Exception:
            return {"valid": False, "errors": ["SE Ranking credential or configuration is invalid"], "satisfied_set": None}

    def _authority(self):
        return _Authority(self.config.credentials)

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        _credential(credential_data)
        return {"valid": None, "error": "Run protected SE Ranking profile evidence; static validation does not prove API eligibility, project ownership or write permissions"}

    async def execute(self, inputs):
        if self.node_data.get("credentials") is not None:
            _family(self.node_data["credentials"])
        client = _Client(self._authority())
        cfg, op = self.config.config, self.config.config.operation
        site = getattr(cfg, "site_id", None)
        if site is not None:
            client.site(site)
        identity = await client.profile()
        if op == "get_profile":
            return identity
        if op == "list_projects":
            return {**identity, **client.local_page(await client.collection("project"), cfg, "project")}
        project = await client.project(site)
        if op == "get_project":
            return {**identity, "data": project}
        if hasattr(cfg, "site_engine_id"):
            await client.engine(site, cfg.site_engine_id)
        collections = {"list_search_engines": "engine", "list_keywords": "keyword", "list_keyword_groups": "group", "list_competitors": "competitor"}
        if op in collections:
            kind = collections[op]
            engine = getattr(cfg, "site_engine_id", None)
            return {**identity, "site_id": site, **client.local_page(await client.collection(kind, site, engine), cfg, kind, engine)}
        if op == "get_project_summary":
            row = await client._http("GET", "/sites/summary", params={"site_id": site})
            if not isinstance(row, dict) or type(row.get("site_id")) is not int or row["site_id"] != site:
                raise ValueError("SE Ranking summary belongs to another project")
            result = {"site_id": site}
            for key in ("today_avg", "yesterday_avg", "total_up", "total_down", "top5", "top10", "top30", "visibility", "visibility_percent", "da", "index_google"):
                if row.get(key) is not None:
                    result[key] = _number(row[key], 0)
            return {**identity, "data": _public(result, client.credential)}
        if op == "get_historical_dates":
            row = await client._http("GET", "/sites/positions/checkpoints", params={"site_id": site, "site_engine_id": cfg.site_engine_id})
            if not isinstance(row, dict):
                raise ValueError("SE Ranking historical date envelope is invalid")
            dates = {key: _date(row[key]) for key in ("current", "day_ago", "7days", "30days", "90days", "180days", "first") if row.get(key) is not None}
            return {**identity, "site_id": site, "site_engine_id": cfg.site_engine_id, "data": dates}
        if op == "get_keyword_positions":
            if cfg.keyword_id not in {row["id"] for row in await client.collection("keyword", site, cfg.site_engine_id)}:
                raise ValueError("SE Ranking keyword belongs to another project")
            engines = await client._http("GET", "/sites/positions", params={"site_id": site, "site_engine_id": cfg.site_engine_id, "date_from": cfg.date_from, "date_to": cfg.date_to})
            if not isinstance(engines, list) or len(engines) > 1:
                raise ValueError("SE Ranking positions exceeded the selected engine boundary")
            selected = []
            for engine in engines:
                if not isinstance(engine, dict) or engine.get("site_engine_id") != cfg.site_engine_id or type(engine.get("site_engine_id")) is not int or not isinstance(engine.get("keywords"), list) or len(engine["keywords"]) > 5000:
                    raise ValueError("SE Ranking positions returned another or malformed engine")
                ids = [_id(row.get("id")) for row in engine["keywords"] if isinstance(row, dict)]
                if len(ids) != len(engine["keywords"]) or len(set(ids)) != len(ids):
                    raise ValueError("SE Ranking position keyword IDs are malformed or repeat")
                for keyword in engine["keywords"]:
                    if _id(keyword["id"]) != cfg.keyword_id:
                        continue
                    positions = keyword.get("positions")
                    if not isinstance(positions, list) or len(positions) > 31:
                        raise ValueError("SE Ranking keyword history exceeds its bound")
                    for position in positions:
                        if not isinstance(position, dict) or not cfg.date_from <= _date(position.get("date")) <= cfg.date_to:
                            raise ValueError("SE Ranking position belongs to another period")
                        projected = {"date": position["date"]}
                        for key in ("pos", "change", "is_map", "map_position", "paid_position"):
                            if position.get(key) is not None:
                                projected[key] = _number(position[key])
                        selected.append(projected)
            if len({row["date"] for row in selected}) != len(selected):
                raise ValueError("SE Ranking history dates repeat")
            return {**identity, "site_id": site, "site_engine_id": cfg.site_engine_id, "keyword_id": cfg.keyword_id, "data": selected}
        if op == "create_keyword_group":
            before = await client.collection("group", site)
            row = await client._http("POST", "/keywords/groups", body={"site_id": site, "name": cfg.name})
            if not isinstance(row, dict):
                raise ValueError("SE Ranking group acknowledgement is malformed; verify before retrying")
            identifier = _id(row.get("group_id"))
            after = await client.collection("group", site)
            matches = [row for row in after if row["id"] == identifier]
            if identifier in {row["id"] for row in before} or len(matches) != 1 or matches[0].get("name") != cfg.name:
                raise ValueError("SE Ranking created group readback differs; verify before retrying")
            return {**identity, "site_id": site, "data": matches[0], "http_status": 201, "readback_verified": True, "ownership_verified": False}
        if op == "delete_keyword_group":
            groups = await client.collection("group", site)
            if cfg.group_id not in {row["id"] for row in groups}:
                raise ValueError("SE Ranking group belongs to another project")
            keywords = await client.collection("keyword", site)
            if any("group_id" not in row for row in keywords) or any(row["group_id"] == cfg.group_id for row in keywords):
                raise ValueError("SE Ranking group is not proven empty")
            await client._http("DELETE", "/keywords/groups", params={"group_id": cfg.group_id})
            if cfg.group_id in {row["id"] for row in await client.collection("group", site)}:
                raise ValueError("SE Ranking deleted group remains present; verify before retrying")
            return {**identity, "site_id": site, "group_id": cfg.group_id, "http_status": 204, "deleted": True, "absence_verified": True}
        if op == "list_audits":
            return {**identity, "site_id": site, **await client.audit_page(site, cfg.page_size, cfg.page_token)}
        if op == "get_audit_status":
            await client.audit_witness(site, cfg.audit_id)
            row = await client._http("GET", "/audits/status", params={"audit_id": cfg.audit_id})
            if not isinstance(row, dict) or row.get("status") not in {"queued", "processing", "finished", "cancelled", "expired"}:
                raise ValueError("SE Ranking audit status is not documented")
            result = {"audit_id": cfg.audit_id, "site_id": site, "status": row["status"]}
            for key in ("total_pages", "total_errors", "total_warnings", "total_passed"):
                if row.get(key) is not None:
                    if type(row[key]) is not int or row[key] < 0:
                        raise ValueError("SE Ranking audit counter is invalid")
                    result[key] = row[key]
            for key in ("start_time", "audit_time"):
                if row.get(key) is not None:
                    result[key] = _text(row[key], 128)
            return {**identity, "data": _public(result, client.credential), "http_status": 200}
        raise ValueError("Unsupported SE Ranking native operation")

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        _credential(credential_data)
        if field_name not in {"site_id", "site_engine_id", "keyword_id", "group_id", "audit_id"}:
            raise ValueError("Unsupported SE Ranking selector")
        authority = _Authority(credential_data)
        client = _Client(authority)
        context = context or {}
        site = client.site(context.get("site_id")) if field_name != "site_id" else None
        await client.profile()
        if site:
            await client.project(site)
        if field_name == "audit_id":
            page = await client.audit_page(site, 50, page_token)
            rows, next_token = page["data"], page["next_page_token"]
        else:
            if page_token is not None:
                raise ValueError("SE Ranking complete-array selectors do not accept provider cursors")
            kind = {"site_id": "project", "site_engine_id": "engine", "keyword_id": "keyword", "group_id": "group"}[field_name]
            engine = _id(context.get("site_engine_id")) if field_name == "keyword_id" else None
            if engine:
                await client.engine(site, engine)
            rows, next_token = await client.collection(kind, site, engine), None
        query = normalize_search(search)
        query = query.casefold() if query else None
        options = [{"value": str(row["id"]), "label": row.get("title") or row.get("name") or ("Engine " + str(row["id"]) if field_name == "site_engine_id" else str(row["id"]))} for row in rows]
        if query:
            options = [row for row in options if query in row["label"].casefold() or query in row["value"]]
        return {"options": options, "next_page_token": next_token}
