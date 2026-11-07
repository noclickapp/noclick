"""Native bounded DataForSEO v3 SEO data workflows.

Issued API Basic credentials stay private. Task acceptance, pending work and
completed/partial results are distinct; raw request echoes and errors are omitted.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
import math
import re
from contextvars import ContextVar
from typing import Annotated, Literal, Optional, Union
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import SSRFError, guarded_async_client

KIND = "dataforseo_basic"
ORIGIN = "https://api.dataforseo.com/v3"
MAX_BYTES = 8 * 1024 * 1024
_private_request = ContextVar("dataforseo_private_request", default=False)


class _PrivateFilter(logging.Filter):
    def filter(self, record):
        return not _private_request.get()


for _name in ("httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool",
              "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"):
    logging.getLogger(_name).addFilter(_PrivateFilter())


def text(value, maximum=1000, *, empty=False):
    if (not isinstance(value, str) or len(value) > maximum or (not value and not empty)
            or re.search(r"[\x00-\x1f\x7f]", value)):
        raise ValueError("DataForSEO returned invalid text metadata.")
    return value


def integer(value, maximum=10**15):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("DataForSEO returned invalid integer metadata.")
    return value


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("DataForSEO returned invalid numeric metadata.")
    return value


def uid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value.lower():
            raise ValueError()
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Supply a canonical DataForSEO task UUID.") from None


def domain(value):
    value = text(value, 253).lower()
    if (value.endswith(".") or not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?", value)
            or value.endswith((".localhost", ".local", ".internal", ".invalid", ".test", ".example"))
            or value in {"localhost", "metadata.google.internal"}):
        raise ValueError("Supply a public domain without a scheme, path, user information or port.")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError("IP targets are not supported by this domain surface.")


def public_url(value):
    value = text(value, 4096)
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or parsed.username is not None
                or parsed.password is not None or "\\" in value or parsed.port not in {None, 80, 443}):
            raise ValueError()
        host = domain(parsed.hostname)
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("DataForSEO returned an unsupported public result URL.") from None


class DataForSEOAPICredential(BaseModel):
    model_config = ConfigDict(extra="ignore", title="DataForSEO API Login", json_schema_extra={
        "x-credential-url": "https://docs.dataforseo.com/v3/auth/",
        "x-credential-instructions": "Supply the login and generated API password from DataForSEO API Access. The API password is different from your console password. No password minting, browser OAuth, sandbox or free-credit eligibility is inferred.",
    })
    credential_type: Literal["dataforseo_basic"] = Field(KIND, json_schema_extra={"ui:hidden": True})
    api_login: StrictStr = Field(..., min_length=1, max_length=320, title="API Login",
        json_schema_extra={"ui:widget": "password"})
    api_password: StrictStr = Field(..., min_length=1, max_length=4096, title="Generated API Password",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_login", "api_password")
    @classmethod
    def issued(cls, value, info):
        text(value, 4096)
        if not value.isascii() or re.search(r"[\x00-\x20\x7f]", value) or (info.field_name == "api_login" and ":" in value):
            raise ValueError("Supply the issued ASCII API login/password pair.")
        return value


def credential(value):
    if isinstance(value, DataForSEOAPICredential):
        value = value.model_dump()
    if not isinstance(value, dict) or value.get("credential_type") != KIND:
        raise ValueError("DataForSEO requires its issued API Basic credential.")
    try:
        return DataForSEOAPICredential.model_validate(value)
    except Exception:
        raise ValueError("Invalid DataForSEO API credential shape.") from None


def raw_tag(data):
    if isinstance(data, dict) and isinstance(data.get("credentials"), dict):
        if data["credentials"].get("credential_type") != KIND:
            raise ConfigValidationError("Credential type is not supported by DataForSEO.")


def op(name, label, *, creates=False):
    extra = {"const": name, "ui:hidden": True, "x-display-name": label}
    if creates:
        extra.update({"x-creates-resource": True, "x-resource-type": "dataforseo_serp_task",
                      "x-resource-id-path": "data.task_id"})
    return Field(name, json_schema_extra=extra)


def locale_field(name, *, integer_code=False, depends=None):
    opts = {"field_name": name, "searchable": True, "allow_custom": True}
    if depends:
        opts["depends_on"] = depends
    return Field(..., title=name.replace("_", " ").title(), json_schema_extra={
        "x-resource-type": "dataforseo_" + name, "x-dynamic-options": opts},
        **({"ge": 1, "le": 100000000} if integer_code else {"min_length": 2, "max_length": 12}))


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("task_id", check_fields=False)
    @classmethod
    def task(cls, value):
        return uid(value)

    @field_validator("target", check_fields=False)
    @classmethod
    def target_domain(cls, value):
        return domain(value)

    @field_validator("keyword", check_fields=False)
    @classmethod
    def keyword_text(cls, value):
        text(value, 700)
        return value

    @field_validator("country_code", check_fields=False)
    @classmethod
    def country(cls, value):
        if not re.fullmatch(r"[a-zA-Z]{2}", value):
            raise ValueError("Use a two-letter country ISO code.")
        return value.lower()

    @field_validator("serp_language_code", "keyword_language_code", "labs_language_code", check_fields=False)
    @classmethod
    def language(cls, value):
        if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z]{2,4})?", value):
            raise ValueError("Use an actual language code from this API family's catalog.")
        return value


class Paging(Input):
    page_size: StrictInt = Field(25, ge=1, le=100)
    page_token: Optional[StrictStr] = Field(None, max_length=24000,
        description="Opaque cursor bound to this credential, operation and all filters. Each live POST page can incur another charge.")


class Catalog(Paging):
    search: Optional[StrictStr] = Field(None, max_length=256)

    @field_validator("search")
    @classmethod
    def search_text(cls, value):
        return text(value, 256) if value is not None else None


class CountryCatalog(Catalog):
    country_code: StrictStr = Field("us", max_length=2,
        description="The documented country filter bounds location discovery.")


class DataForSEOAccount(Input):
    operation: Literal["get_account_metadata"] = op("get_account_metadata", "Get Account Metadata")


class DataForSEOSerpLocations(CountryCatalog):
    operation: Literal["list_serp_locations"] = op("list_serp_locations", "List Google SERP Locations")


class DataForSEOSerpLanguages(Catalog):
    operation: Literal["list_serp_languages"] = op("list_serp_languages", "List Google SERP Languages")


class DataForSEOKeywordLocations(CountryCatalog):
    operation: Literal["list_keyword_locations"] = op("list_keyword_locations", "List Google Ads Locations")


class DataForSEOKeywordLanguages(Catalog):
    operation: Literal["list_keyword_languages"] = op("list_keyword_languages", "List Google Ads Languages")


class DataForSEOLabsLocales(Catalog):
    operation: Literal["list_labs_locations_and_languages"] = op("list_labs_locations_and_languages", "List Google Labs Locations and Languages")
    for_location_code: Optional[StrictInt] = Field(None, ge=1, le=100000000,
        description="Optionally return only the Google-supported languages for this actual Labs location.")


class SerpInput(Input):
    country_code: StrictStr = Field("us", max_length=2)
    serp_location_code: StrictInt = locale_field("serp_location_code", integer_code=True, depends=["country_code"])
    serp_language_code: StrictStr = locale_field("serp_language_code")
    keyword: StrictStr = Field(..., min_length=1, max_length=700)
    device: Literal["desktop", "mobile"] = "desktop"
    os: Optional[Literal["windows", "macos", "android", "ios"]] = None
    depth: StrictInt = Field(10, ge=1, le=100, description="More requested results may increase the provider charge.")

    @model_validator(mode="after")
    def platform(self):
        if self.os is not None and self.os not in ({"windows", "macos"} if self.device == "desktop" else {"android", "ios"}):
            raise ValueError("The operating system must match the selected SERP device.")
        return self


class DataForSEOSubmitSerp(SerpInput):
    operation: Literal["submit_google_organic_task"] = op("submit_google_organic_task", "Submit Google Organic SERP Task", creates=True)


class DataForSEOReadyTasks(Paging):
    operation: Literal["list_ready_google_organic_tasks"] = op("list_ready_google_organic_tasks", "List Ready Google Organic Tasks")


class DataForSEOGetSerp(Input):
    operation: Literal["get_google_organic_task_results"] = op("get_google_organic_task_results", "Get Google Organic Task Results")
    task_id: StrictStr = Field(..., description="Actual task UUID. Retrieval removes the task from the provider's ready list.",
        json_schema_extra={"x-resource-type": "dataforseo_serp_task"})


class DataForSEOSearchVolume(Input):
    operation: Literal["get_keyword_search_volume"] = op("get_keyword_search_volume", "Get Google Ads Search Volume")
    country_code: StrictStr = Field("us", max_length=2)
    keyword_location_code: StrictInt = locale_field("keyword_location_code", integer_code=True, depends=["country_code"])
    keyword_language_code: StrictStr = locale_field("keyword_language_code")
    keywords: list[StrictStr] = Field(..., min_length=1, max_length=100)
    search_partners: StrictBool = False

    @field_validator("keywords")
    @classmethod
    def bounded_keywords(cls, values):
        for value in values:
            text(value, 80)
            if len(value.split()) > 10:
                raise ValueError("Google Ads keywords must contain at most ten words.")
        if len(set(value.casefold() for value in values)) != len(values):
            raise ValueError("Supply distinct keywords ignoring case.")
        return values


class LabsLocale(Input):
    labs_location_code: StrictInt = locale_field("labs_location_code", integer_code=True)
    labs_language_code: StrictStr = locale_field("labs_language_code", depends=["labs_location_code"])


class DataForSEORelatedKeywords(LabsLocale, Paging):
    operation: Literal["get_related_keywords"] = op("get_related_keywords", "Get Google Related Keywords")
    keyword: StrictStr = Field(..., min_length=1, max_length=700)
    depth: StrictInt = Field(1, ge=0, le=4)
    include_seed_keyword: StrictBool = False


class DataForSEODomainOverview(LabsLocale):
    operation: Literal["get_domain_rank_overview"] = op("get_domain_rank_overview", "Get Google Domain Rank Overview")
    target: StrictStr = Field(..., min_length=3, max_length=253)


class DataForSEORankedKeywords(LabsLocale, Paging):
    operation: Literal["get_ranked_keywords"] = op("get_ranked_keywords", "Get Google Ranked Keywords")
    target: StrictStr = Field(..., min_length=3, max_length=253)
    ignore_synonyms: StrictBool = False


class BacklinkInput(Input):
    target: StrictStr = Field(..., min_length=3, max_length=253)
    include_subdomains: StrictBool = True
    exclude_internal_backlinks: StrictBool = True
    backlinks_status_type: Literal["live", "lost", "all"] = "live"


class DataForSEOBacklinksSummary(BacklinkInput):
    operation: Literal["get_backlinks_summary"] = op("get_backlinks_summary", "Get Backlinks Summary")
    include_indirect_links: StrictBool = True


class DataForSEOBacklinks(BacklinkInput, Paging):
    operation: Literal["get_backlinks"] = op("get_backlinks", "Get Backlinks")
    mode: Literal["as_is", "one_per_domain", "one_per_anchor"] = "as_is"


Operations = Annotated[Union[DataForSEOAccount, DataForSEOSerpLocations, DataForSEOSerpLanguages,
    DataForSEOKeywordLocations, DataForSEOKeywordLanguages, DataForSEOLabsLocales,
    DataForSEOSubmitSerp, DataForSEOReadyTasks, DataForSEOGetSerp, DataForSEOSearchVolume,
    DataForSEORelatedKeywords, DataForSEODomainOverview, DataForSEORankedKeywords,
    DataForSEOBacklinksSummary, DataForSEOBacklinks], Field(discriminator="operation")]


class DataForSEOConfiguration(NodeConfig[Operations, DataForSEOAPICredential]):
    pass


ROUTES = {
    "get_account_metadata": ("GET", "/appendix/user_data"),
    "list_serp_locations": ("GET", "/serp/google/locations"),
    "list_serp_languages": ("GET", "/serp/google/languages"),
    "list_keyword_locations": ("GET", "/keywords_data/google_ads/locations"),
    "list_keyword_languages": ("GET", "/keywords_data/google_ads/languages"),
    "list_labs_locations_and_languages": ("GET", "/dataforseo_labs/locations_and_languages"),
    "submit_google_organic_task": ("POST", "/serp/google/organic/task_post"),
    "list_ready_google_organic_tasks": ("GET", "/serp/google/organic/tasks_ready"),
    "get_google_organic_task_results": ("GET", "/serp/google/organic/task_get/advanced"),
    "get_keyword_search_volume": ("POST", "/keywords_data/google_ads/search_volume/live"),
    "get_related_keywords": ("POST", "/dataforseo_labs/google/related_keywords/live"),
    "get_domain_rank_overview": ("POST", "/dataforseo_labs/google/domain_rank_overview/live"),
    "get_ranked_keywords": ("POST", "/dataforseo_labs/google/ranked_keywords/live"),
    "get_backlinks_summary": ("POST", "/backlinks/summary/live"),
    "get_backlinks": ("POST", "/backlinks/backlinks/live"),
}


class ProviderStatusError(ValueError):
    def __init__(self, code):
        self.provider_status = code
        super().__init__(f"DataForSEO provider status {code}; the requested operation did not complete.")


def envelope(value, operation, *, task_id=None):
    if (not isinstance(value, dict) or type(value.get("status_code")) is not int
            or type(value.get("tasks_count")) is not int or type(value.get("tasks_error")) is not int):
        raise ValueError("DataForSEO returned a malformed task envelope.")
    if value["status_code"] != 20000:
        raise ProviderStatusError(value["status_code"])
    tasks = value.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 1 or value["tasks_count"] != 1 or not 0 <= value["tasks_error"] <= 1:
        raise ValueError("DataForSEO returned an unexpected task count.")
    task = tasks[0]
    if not isinstance(task, dict) or type(task.get("status_code")) is not int:
        raise ValueError("DataForSEO returned malformed task metadata.")
    task_uid = uid(task.get("id"))
    if task_id is not None and task_uid != task_id:
        raise ValueError("DataForSEO returned a different task UUID.")
    code = task["status_code"]
    accepted = operation == "submit_google_organic_task" and code == 20100
    pending = operation == "get_google_organic_task_results" and code in {40601, 40602}
    partial = operation == "get_google_organic_task_results" and code == 40106
    no_results = operation != "submit_google_organic_task" and code == 40102
    if code != 20000 and not (accepted or pending or partial or no_results):
        raise ProviderStatusError(code)
    if operation == "submit_google_organic_task" and not accepted:
        raise ValueError("DataForSEO task submission did not return Task Created.")
    if code == 20000 and value["tasks_error"]:
        raise ValueError("DataForSEO task-error count contradicts successful task status.")
    count = integer(task.get("result_count"), 100000)
    result = task.get("result")
    if result is None:
        if count != 0 or not (accepted or pending or no_results):
            raise ValueError("DataForSEO returned missing completed results.")
        result = []
    if not isinstance(result, list) or len(result) != count or len(result) > 100000:
        raise ValueError("DataForSEO returned malformed result-count metadata.")
    if (accepted or pending) and result:
        raise ValueError("DataForSEO returned results for an incomplete task.")
    cost = number(task.get("cost"))
    number(value.get("cost"))
    return result, {"task_id": task_uid, "provider_status": code, "cost_usd": cost,
        "accepted": accepted, "completed": not (accepted or pending), "pending": pending, "partial": partial,
        "no_results": no_results}


def obj(value):
    if not isinstance(value, dict):
        raise ValueError("DataForSEO returned malformed result metadata.")
    return value


def select(value, *, strings=(), numbers=(), integers=(), booleans=(), urls=()):
    value = obj(value)
    result = {}
    for keys, validate in ((strings, text), (numbers, number), (integers, integer), (urls, public_url)):
        for key in keys:
            if key in value:
                result[key] = validate(value[key]) if value[key] is not None else None
    for key in booleans:
        if key in value:
            if value[key] is not None and type(value[key]) is not bool:
                raise ValueError("DataForSEO returned invalid Boolean metadata.")
            result[key] = value[key]
    return result


def location(value, *, labs=False):
    result = select(value, strings=("location_name", "country_iso_code", "location_type"),
        integers=("location_code", "location_code_parent"))
    if not isinstance(result.get("location_code"), int) or not result.get("location_name"):
        raise ValueError("DataForSEO returned malformed location metadata.")
    if labs:
        languages = obj(value).get("available_languages")
        if not isinstance(languages, list) or len(languages) > 500:
            raise ValueError("DataForSEO returned malformed Labs language metadata.")
        result["available_languages"] = []
        for row in languages:
            sources = obj(row).get("available_sources")
            if not isinstance(sources, list) or any(not isinstance(s, str) for s in sources):
                raise ValueError("DataForSEO returned malformed Labs sources.")
            if "google" in sources:
                result["available_languages"].append(language(row))
    return result


def language(value):
    value = obj(value)
    return {"language_code": text(value.get("language_code"), 12),
            "language_name": text(value.get("language_name"), 128)}


def keyword_data(value):
    value = obj(value)
    result = {"keyword": text(value.get("keyword"), 700)}
    info = value.get("keyword_info")
    if info is not None:
        result["keyword_info"] = select(info, strings=("competition_level", "last_updated_time"),
            numbers=("competition", "cpc", "low_top_of_page_bid", "high_top_of_page_bid"),
            integers=("search_volume",))
    return result


METRICS = ("pos_1", "pos_2_3", "pos_4_10", "pos_11_20", "pos_21_30", "pos_31_40",
           "pos_41_50", "pos_51_60", "pos_61_70", "pos_71_80", "pos_81_90", "pos_91_100",
           "count", "etv", "estimated_paid_traffic_cost", "is_new", "is_up", "is_down", "is_lost")


def metrics(value):
    value = obj(value)
    return {key: select(value[key], numbers=METRICS) for key in ("organic", "paid") if value.get(key) is not None}


def binding(creds):
    return json.dumps(creds.model_dump(), sort_keys=True, separators=(",", ":"))


def cipher(creds):
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("dataforseo-cursor:" + binding(creds)).encode()).digest()))


def cursor_context(cfg, creds):
    return {"grant": hashlib.sha256(binding(creds).encode()).hexdigest(),
            "config": cfg.model_dump(exclude={"page_token"})}


def unpack_cursor(cfg, creds):
    if cfg.page_token is None:
        return 0, None, []
    try:
        value = json.loads(cipher(creds).decrypt(cfg.page_token.encode()))
        if value["context"] != cursor_context(cfg, creds):
            raise ValueError()
        offset = integer(value["offset"], 3000)
        seen = value["seen"]
        if (offset == 0 or not isinstance(seen, list) or not 1 <= len(seen) <= 30
                or any(type(item) is not int or item < 1 for item in seen) or offset != seen[-1]
                or seen != sorted(set(seen))):
            raise ValueError()
        return offset, value.get("fingerprint"), seen
    except (InvalidToken, ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("DataForSEO cursor differs from the current credential or filters.") from None


def pack_cursor(offset, fingerprint, seen, cfg, creds):
    if offset > 3000 or len(seen) >= 30 or offset in seen:
        raise ValueError("DataForSEO pagination exceeds the bounded cursor window.")
    return cipher(creds).encrypt(json.dumps({"context": cursor_context(cfg, creds), "offset": offset,
        "fingerprint": fingerprint, "seen": seen + [offset]}, sort_keys=True).encode()).decode()


def page_local(rows, cfg, creds):
    offset, previous, seen = unpack_cursor(cfg, creds)
    if isinstance(cfg, Catalog) and cfg.search is not None:
        query = cfg.search.casefold()
        rows = [row for row in rows if query in json.dumps(row, ensure_ascii=False).casefold()]
    fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    if previous is not None and previous != fingerprint:
        raise ValueError("DataForSEO catalog/ready inventory changed; restart pagination.")
    if offset > len(rows):
        raise ValueError("DataForSEO cursor lies beyond this result list.")
    chosen = rows[offset:offset + cfg.page_size]
    more = offset + len(chosen) < len(rows)
    return {"items": chosen, "total": len(rows), "has_more": more,
            "next_page_token": pack_cursor(offset + len(chosen), fingerprint, seen, cfg, creds) if more else None}


class DataForSEONode(WorkflowNode):
    integration_type = "automation-dataforseo"
    agent_tool_provider = True
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(noun="account", identity_operation="get_account_metadata",
        identity_keys=("login",), proves="account")

    @classmethod
    def get_config_model(cls):
        return DataForSEOConfiguration

    @classmethod
    def parse_config(cls, config_data):
        raw_tag(config_data)
        try:
            return DataForSEOConfiguration.model_validate(config_data)
        except Exception:
            raise ConfigValidationError("Invalid DataForSEO configuration or credential shape.") from None

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls.parse_config(config_data)
            return {"valid": True, "errors": [], "satisfied_set": "default"}
        except Exception:
            return {"valid": False, "errors": ["Invalid DataForSEO configuration or credential shape."], "satisfied_set": None}

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Staging resolves saved-row access before this hook. Issued API Basic
        # credentials do not have a refresh flow.
        return credential(credential_data).model_dump()

    async def _current(self):
        raw_tag(self.node_data)
        if not isinstance(self.config, DataForSEOConfiguration) or self.config.credentials is None:
            raise ValueError("DataForSEO API credentials are required.")
        return credential(self.config.credentials)

    def _binding(self, creds):
        return binding(creds)

    async def _request(self, cfg, expected):
        creds = await self._current()
        if self._binding(creds) != expected:
            raise ValueError("DataForSEO credential authority changed before the request.")
        method, suffix = ROUTES[cfg.operation]
        if isinstance(cfg, CountryCatalog):
            suffix += "/" + cfg.country_code
        if isinstance(cfg, DataForSEOGetSerp):
            suffix += "/" + cfg.task_id
        body = None
        if method == "POST":
            body = cfg.model_dump(exclude={"operation", "country_code", "page_token", "page_size"})
            for family in ("serp", "keyword", "labs"):
                for key in ("location_code", "language_code"):
                    field = family + "_" + key
                    if field in body:
                        body[key] = body.pop(field)
            body = {key: value for key, value in body.items() if value is not None}
            if isinstance(cfg, (DataForSEORelatedKeywords, DataForSEORankedKeywords, DataForSEOBacklinks)):
                body.update(limit=cfg.page_size, offset=unpack_cursor(cfg, creds)[0])
            if isinstance(cfg, DataForSEORankedKeywords):
                body["item_types"] = ["organic"]
                body["include_clickstream_data"] = False
            if isinstance(cfg, DataForSEORelatedKeywords):
                body["include_serp_info"] = False
                body["include_clickstream_data"] = False
            body = [body]
        marker = _private_request.set(True)
        header = "Basic " + base64.b64encode((creds.api_login + ":" + creds.api_password).encode("ascii")).decode("ascii")
        try:
            async with guarded_async_client( trust_env=False, follow_redirects=False, timeout=120) as client:
                async with client.stream(method, ORIGIN + suffix, json=body,
                        headers={"Authorization": header, "Accept": "application/json", "Content-Type": "application/json"}) as response:
                    if response.status_code != 200:
                        safe = httpx.Request(method, "https://dataforseo.invalid/api/")
                        raise httpx.HTTPStatusError(f"DataForSEO HTTP {response.status_code}; operation did not complete.",
                            request=safe, response=httpx.Response(response.status_code, request=safe))
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES:
                            raise ValueError("DataForSEO response exceeds the 8 MiB client bound.")
                    try:
                        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    except Exception:
                        raise ValueError("DataForSEO returned malformed JSON.") from None
        except httpx.HTTPStatusError:
            raise
        except (httpx.RequestError, SSRFError):
            raise ValueError("DataForSEO request failed; completion is unverified and no automatic retry was made.") from None
        finally:
            _private_request.reset(marker)
        if self._binding(await self._current()) != expected:
            raise ValueError("DataForSEO credential authority changed during the request.")
        return envelope(value, cfg.operation, task_id=getattr(cfg, "task_id", None))

    async def execute(self, inputs):
        creds = await self._current()
        cfg = self.config.config
        rows, task = await self._request(cfg, self._binding(creds))
        if task["accepted"] or task["pending"]:
            return {"status": "success", "data": task}
        if isinstance(cfg, DataForSEOAccount):
            if len(rows) != 1:
                raise ValueError("DataForSEO returned malformed account metadata.")
            row = obj(rows[0])
            if text(row.get("login"), 320) != creds.api_login:
                raise ValueError("DataForSEO returned a different API account login.")
            data = select(row, strings=("login", "timezone"))
        elif isinstance(cfg, (DataForSEOSerpLocations, DataForSEOKeywordLocations)):
            data = page_local([location(row) for row in rows], cfg, creds)
        elif isinstance(cfg, (DataForSEOSerpLanguages, DataForSEOKeywordLanguages)):
            data = page_local([language(row) for row in rows], cfg, creds)
        elif isinstance(cfg, DataForSEOLabsLocales):
            locales = [location(row, labs=True) for row in rows]
            if cfg.for_location_code is not None:
                matches = [row for row in locales if row["location_code"] == cfg.for_location_code]
                if len(matches) != 1:
                    raise ValueError("DataForSEO did not return the requested Labs parent location.")
                locales = matches[0]["available_languages"]
            data = page_local(locales, cfg, creds)
        elif isinstance(cfg, DataForSEOReadyTasks):
            if len(rows) > 1000:
                raise ValueError("DataForSEO ready list exceeds its documented 1000-task bound.")
            projected = []
            for row in rows:
                row = obj(row)
                if row.get("se") != "google" or row.get("se_type") != "organic":
                    raise ValueError("DataForSEO returned a different SERP task family.")
                projected.append({"id": uid(row.get("id")), **select(row, strings=("date_posted",))})
            data = page_local(projected, cfg, creds)
            data["provider_window"] = "At most 1000 uncollected tasks completed in the previous three days."
        elif isinstance(cfg, DataForSEOGetSerp):
            result = []
            for row in rows:
                row = obj(row)
                items = row.get("items")
                if items is None and row.get("items_count") == 0:
                    items = []
                if not isinstance(items, list) or len(items) > 1000 or integer(row.get("items_count")) != len(items):
                    raise ValueError("DataForSEO returned malformed SERP items.")
                projected = []
                for item in items:
                    item = obj(item)
                    if item.get("type") == "organic":
                        projected.append({"type": "organic", **select(item, strings=("domain", "title", "description"),
                            integers=("rank_group", "rank_absolute"), urls=("url",))})
                result.append({**select(row, strings=("keyword", "language_code", "datetime"), integers=("location_code", "se_results_count", "items_count")),
                    "items": projected, "projection": "organic_only"})
            data = {"results": result}
        elif isinstance(cfg, DataForSEOSearchVolume):
            if len(rows) > len(cfg.keywords):
                raise ValueError("DataForSEO returned excess keyword results.")
            projected = []
            for row in rows:
                row = obj(row)
                word = text(row.get("keyword"), 80)
                if word.casefold() not in {keyword.casefold() for keyword in cfg.keywords}:
                    raise ValueError("DataForSEO returned an unrequested keyword.")
                projected.append({"keyword": word, **select(row, strings=("competition",),
                    numbers=("cpc",), integers=("search_volume", "competition_index"))})
            data = {"items": projected}
        elif isinstance(cfg, DataForSEOBacklinksSummary):
            if len(rows) != 1 or obj(rows[0]).get("target") != cfg.target:
                raise ValueError("DataForSEO returned a different backlinks target.")
            data = select(rows[0], strings=("target", "first_seen", "lost_date"),
                integers=("rank", "backlinks", "referring_domains", "referring_main_domains", "referring_pages",
                          "referring_ips", "referring_subnets", "broken_backlinks", "broken_pages", "external_links_count",
                          "internal_links_count"))
        else:
            data = self._live_results(rows, cfg, creds)
        return {"status": "success", "data": {**task, **data}}

    def _live_results(self, rows, cfg, creds):
        if not rows:
            return {"items": [], "total": 0, "has_more": False, "next_page_token": None}
        if len(rows) != 1:
            raise ValueError("DataForSEO returned unexpected live result count.")
        result = obj(rows[0])
        if getattr(cfg, "target", result.get("target")) != result.get("target"):
            raise ValueError("DataForSEO returned a different query target.")
        if isinstance(cfg, LabsLocale):
            if result.get("location_code") != cfg.labs_location_code or result.get("language_code") != cfg.labs_language_code:
                raise ValueError("DataForSEO returned a different Labs locale.")
        items = result.get("items")
        if items is None and result.get("items_count") == 0:
            items = []
        if not isinstance(items, list) or integer(result.get("items_count")) != len(items):
            raise ValueError("DataForSEO returned malformed live items.")
        total = integer(result.get("total_count"))
        projected = []
        for item in items:
            item = obj(item)
            if isinstance(cfg, DataForSEODomainOverview):
                projected.append({"metrics": metrics(item.get("metrics"))})
            elif isinstance(cfg, (DataForSEORelatedKeywords, DataForSEORankedKeywords)):
                row = keyword_data(item.get("keyword_data"))
                if isinstance(cfg, DataForSEORankedKeywords):
                    element = obj(item.get("ranked_serp_element"))
                    serp = obj(element.get("serp_item"))
                    if serp.get("type") != "organic":
                        raise ValueError("DataForSEO returned a non-organic ranked keyword.")
                    row["serp_item"] = select(serp, strings=("domain", "title"), integers=("rank_group", "rank_absolute"), urls=("url",))
                projected.append(row)
            else:
                projected.append(select(item, strings=("domain_from", "domain_to", "first_seen", "last_seen"),
                    integers=("rank", "page_from_rank", "domain_from_rank", "page_from_status_code", "url_to_status_code"),
                    booleans=("dofollow", "is_broken", "is_indirect_link"), urls=("url_from", "url_to")))
        if isinstance(cfg, Paging):
            offset, _, seen = unpack_cursor(cfg, creds)
            if len(items) > cfg.page_size or offset + len(items) > total or (not items and offset < total):
                raise ValueError("DataForSEO returned inconsistent live pagination.")
            more = offset + len(items) < total
            nxt = pack_cursor(offset + len(items), None, seen, cfg, creds) if more else None
        else:
            if len(items) > 1000:
                raise ValueError("DataForSEO overview exceeds the bounded result window.")
            more, nxt = False, None
        data = {"items": projected, "total": total, "has_more": more, "next_page_token": nxt}
        if isinstance(cfg, DataForSEORelatedKeywords) and cfg.include_seed_keyword and result.get("seed_keyword_data") is not None:
            data["seed_keyword_data"] = keyword_data(result["seed_keyword_data"])
        return data

    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        if validation_context is None:
            return {"valid": None, "message": "DataForSEO account access is unverified; authenticated validation context is required."}
        try:
            creds = credential(credential_data)
            result = await validation_context.run_operation("get_account_metadata", {})
            if (result.get("executed") is False or result.get("_halt_downstream")
                    or result.get("status") != "success"):
                return {"valid": None, "message": "DataForSEO account access is unverified."}
            if result.get("status") == "success" and result.get("data", {}).get("login") == creds.api_login:
                return {"valid": True, "message": "DataForSEO returned this API account login. Paid endpoint access remains provider-enforced."}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                return {"valid": False, "message": f"DataForSEO rejected the account probe (HTTP {exc.response.status_code})."}
        except ProviderStatusError as exc:
            if exc.provider_status == 40100:
                return {"valid": False, "message": "DataForSEO rejected the API credential."}
        except Exception:
            pass
        return {"valid": None, "message": "DataForSEO account access is unverified."}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search_query=None, page_token=None, **kwargs):
        context = context or {}
        families = {"serp": ("list_serp_locations", "list_serp_languages"),
                    "keyword": ("list_keyword_locations", "list_keyword_languages")}
        creds = credential(credential_data)
        search = search_query if search_query is not None else kwargs.get("search")
        if field_name in {"serp_location_code", "serp_language_code", "keyword_location_code", "keyword_language_code"}:
            family = field_name.split("_", 1)[0]
            location_field = field_name.endswith("location_code")
            cfg = {"operation": families[family][0 if location_field else 1], "page_size": 100,
                   "search": search, "page_token": page_token}
            if location_field:
                cfg["country_code"] = context.get("country_code")
        elif field_name in {"labs_location_code", "labs_language_code"}:
            cfg = {"operation": "list_labs_locations_and_languages", "page_size": 100,
                   "page_token": page_token, "search": search}
            if field_name == "labs_language_code":
                parent = context.get("labs_location_code")
                if type(parent) is not int:
                    raise ValueError("Select a Labs location before loading its language options.")
                cfg["for_location_code"] = parent
        else:
            return {"options": [], "has_more": False}
        node = cls("dataforseo-picker", "automation-dataforseo", {"credentials": creds.model_dump()},
            cls.parse_config({"credentials": creds.model_dump(), "config": cfg}))
        result = (await node.execute({}))["data"]
        rows = result["items"]
        key = "location" if field_name.endswith("location_code") else "language"
        return {"options": [{"value": row[key + "_code"], "label": row[key + "_name"]} for row in rows],
                "has_more": result["has_more"], "next_page_token": result["next_page_token"]}
