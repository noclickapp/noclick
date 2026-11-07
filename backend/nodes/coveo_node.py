"""Closed Coveo search, index metadata and source lifecycle workflows.

Search/Admin use current organization endpoints; Push uses a fixed regional host.
No query passthrough, permission bypass, identity impersonation, key management,
document downloads, security-provider changes or generative/model calls.
"""
from __future__ import annotations
import base64
import contextvars
import hashlib
import hmac
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Discriminator, Field, StringConstraints, TypeAdapter, field_validator
from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.coveo import COVEO_SCOPES
from utils.ssrf import assert_exact_url_origin, guarded_async_client

ID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,255}$")]
FIELD_ID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,127}$")]
MAX_JSON = 2 * 1024 * 1024
PUSH_HOSTS = {"us": "api.cloud.coveo.com", "ca": "api-ca.cloud.coveo.com", "eu": "api-eu.cloud.coveo.com", "au": "api-au.cloud.coveo.com", "hipaa": "apihipaa.cloud.coveo.com"}
LIFECYCLE = {"full_refresh_source": "fullRefresh", "incremental_refresh_source": "incrementalRefresh", "rebuild_source": "rebuild", "pause_source_refresh": "pauseRefresh", "resume_source_refresh": "resumeRefresh"}
STATUS_TYPES = {"CREATING", "DISABLED", "REFRESHING", "PAUSED", "PAUSED_ON_ERROR", "IDLE", "ERROR", "PUSH_READY", "DELETING"}
_PRIVATE = contextvars.ContextVar("coveo_private_transport", default=False)

class _PrivateFilter(logging.Filter):
    def filter(self, record): return not _PRIVATE.get()

for _logger in ("httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks_proxy"):
    logging.getLogger(_logger).addFilter(_PrivateFilter())

class CoveoDenied(ValueError): pass
class CoveoUnavailable(ValueError): pass
class _AuthorityChanged(CoveoUnavailable): pass

def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,255}", value): raise ValueError("Supply an actual bounded Coveo resource ID.")
    return value

def _text(value, maximum=512, *, empty=False):
    if not isinstance(value, str) or not (0 if empty else 1) <= len(value) <= maximum or any(ord(c) < 32 or ord(c) == 127 for c in value): raise ValueError("Supply bounded Coveo text without controls.")
    return value

def _count(value):
    if type(value) is not int or value < 0: raise CoveoUnavailable("Coveo returned malformed counts.")
    return value

class CoveoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Coveo API Key", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://docs.coveo.com/en/1718/"})
    credential_type: Literal["coveo_api_key"] = Field("coveo_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., repr=False, json_schema_extra={"ui:widget": "password"}, description="Already issued Coveo API key, kept on the backend and sent only as Bearer. No browser token, OAuth flow, search-token mint or refresh is configured.")
    organization_id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]{0,62}$", description="Exact permanent organization ID; determines fixed Search/Admin host and path. Never a caller URL.")
    region: Literal["us", "ca", "eu", "au", "hipaa"] = Field("us", description="Actual primary deployment region. Push requires this region; current Search/Admin roots route by organization. HIPAA explicitly selects orghipaa hosts.")
    connection_probe: Literal["search", "organization"] = Field("search", description="Search performs an empty protected query and does not claim a person or organization name. Organization performs a protected organization read and requires Organization - View.")
    search_hub: str = Field("NoClick", max_length=128, description="Use the search hub enforced by your key if it has one. Actual key/pipeline restrictions remain authoritative.")
    allow_management_writes: bool = Field(False, strict=True, description="Off by default. Allows source refresh/rebuild/pause/resume and Push status updates, which affect indexed content/jobs and activity logs; notifications are not assumed suppressed.")
    allow_content_read: bool = Field(False, strict=True, description="Off by default. Explicit search excerpts may reveal indexed private text. Document/media URLs, raw fields, content and credentials are always withheld.")
    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 32768 or any(ord(c) < 33 or ord(c) > 126 for c in value): raise ValueError("Supply issued Coveo key material without whitespace.")
        return value
    @field_validator("search_hub", mode="before")
    @classmethod
    def hub(cls, value): return _text(value, 128)

def _credential(value):
    if isinstance(value, CoveoAPIKeyCredential): return value
    if not isinstance(value, dict) or value.get("credential_type") != "coveo_api_key": raise ValueError("Attach the native Coveo API key family.")
    try: return CoveoAPIKeyCredential.model_validate({key: item for key, item in value.items() if key not in ("token_version", "updated_at")})
    except Exception: raise ValueError("Check the native Coveo API key, organization, region and current policy.") from None

class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    @field_validator("query", "filter", mode="before", check_fields=False)
    @classmethod
    def text(cls, value): return _text(value, 1024, empty=True)
    @field_validator("source_id", mode="before", check_fields=False)
    @classmethod
    def selected(cls, value): return _id(value)
    @field_validator("management_confirmed", mode="before", check_fields=False)
    @classmethod
    def confirmation(cls, value):
        if type(value) is not bool or value is not True: raise ValueError("Explicit management confirmation must be Boolean true.")
        return value

def _op(value, label, category="Index Metadata"):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})

def _selector(kind):
    return {"x-resource-type": "coveo_" + kind, "x-dynamic-options": {"field_name": kind + "_id", "searchable": True, "allow_custom": True}}

class _Source(_Config):
    source_id: ID = Field(..., json_schema_extra=_selector("source"), description="Actual source read through the selected organization endpoint before dependent operations.")
class _Page(_Config):
    per_page: int = Field(25, strict=True, ge=1, le=100)
    page_token: Optional[str] = Field(None, max_length=8192, description="Native continuation bound to credential, organization, region, policy and filters; no provider URL is followed.")
    filter: str = Field("", max_length=1024)
class _Search(_Config):
    query: str = Field("", max_length=1024, description="Basic indexed query. Advanced query syntax is disabled; no additional JSON, identities or permission flags.")
    locale: str = Field("en-US", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
class CoveoTestConfig(_Config):
    operation: Literal["test_connection"] = _op("test_connection", "Test Current Key and Selected Endpoint", "Connection")
class CoveoOrganizationConfig(_Config):
    operation: Literal["get_organization"] = _op("get_organization", "Get Selected Organization Metadata")
class CoveoSourcesConfig(_Page):
    operation: Literal["list_sources"] = _op("list_sources", "List Source Metadata")
class CoveoSourceConfig(_Source):
    operation: Literal["get_source"] = _op("get_source", "Get Source Status")
class CoveoItemTypesConfig(_Source):
    operation: Literal["list_source_item_types"] = _op("list_source_item_types", "List Source Item Types")
class CoveoSchedulesConfig(_Source):
    operation: Literal["list_source_schedules"] = _op("list_source_schedules", "List Source Refresh Schedules")
class CoveoFieldsConfig(_Page):
    operation: Literal["list_fields"] = _op("list_fields", "List Index Fields")
    facets_only: bool = Field(False, strict=True)
class CoveoFieldConfig(_Config):
    operation: Literal["get_field"] = _op("get_field", "Get Index Field Metadata")
    field_id: FIELD_ID = Field(..., json_schema_extra=_selector("field"))
class CoveoSearchConfig(_Search):
    operation: Literal["search"] = _op("search", "Search Indexed Metadata", "Search")
    per_page: int = Field(25, strict=True, ge=1, le=100)
    page_token: Optional[str] = Field(None, max_length=8192)
    include_excerpt: bool = Field(False, strict=True, description="Requires current content-read permission. Excerpts are bounded private workflow output; raw content/URLs remain withheld.")
class CoveoFacetConfig(_Search):
    operation: Literal["query_facets"] = _op("query_facets", "Query Specific Facet Values", "Search")
    field_id: FIELD_ID = Field(..., json_schema_extra=_selector("field"), description="An actual facet-enabled index field; provider remains authoritative.")
    number_of_values: int = Field(8, strict=True, ge=1, le=100)
    selected_values: list[str] = Field(default_factory=list, max_length=20)
    @field_validator("selected_values")
    @classmethod
    def selections(cls, values):
        values = [_text(value, 256) for value in values]
        if len(set(values)) != len(values): raise ValueError("Use unique facet selections.")
        return values
class _Management(_Source):
    management_confirmed: Literal[True] = Field(..., description="Explicit source lifecycle/status action. It changes the provider; acceptance does not prove job completion.")
class CoveoFullRefreshConfig(_Management):
    operation: Literal["full_refresh_source"] = _op("full_refresh_source", "Request Source Rescan", "Source Management")
class CoveoIncrementalConfig(_Management):
    operation: Literal["incremental_refresh_source"] = _op("incremental_refresh_source", "Request Incremental Source Refresh", "Source Management")
class CoveoRebuildConfig(_Management):
    operation: Literal["rebuild_source"] = _op("rebuild_source", "Request Source Rebuild", "Source Management")
class CoveoPauseConfig(_Management):
    operation: Literal["pause_source_refresh"] = _op("pause_source_refresh", "Pause Source Refresh", "Source Management")
class CoveoResumeConfig(_Management):
    operation: Literal["resume_source_refresh"] = _op("resume_source_refresh", "Resume Source Refresh", "Source Management")
class CoveoPushStatusConfig(_Management):
    operation: Literal["set_push_source_status"] = _op("set_push_source_status", "Set Push Source Activity Status", "Source Management")
    status_type: Literal["IDLE", "INCREMENTAL", "REBUILD", "REFRESH"] = Field(..., description="Updates status/activity only; it does not push documents or prove indexing finished. REFRESH means rescan; INCREMENTAL means refresh.")

CoveoOperation = Annotated[Union[CoveoTestConfig, CoveoOrganizationConfig, CoveoSourcesConfig, CoveoSourceConfig, CoveoItemTypesConfig, CoveoSchedulesConfig, CoveoFieldsConfig, CoveoFieldConfig, CoveoSearchConfig, CoveoFacetConfig, CoveoFullRefreshConfig, CoveoIncrementalConfig, CoveoRebuildConfig, CoveoPauseConfig, CoveoResumeConfig, CoveoPushStatusConfig], Discriminator("operation")]
class CoveoNodeConfig(NodeConfig[CoveoOperation, CoveoAPIKeyCredential]): pass

def _roots(credential):
    suffix = "orghipaa.coveo.com" if credential.region == "hipaa" else "org.coveo.com"
    return {"search": "https://" + credential.organization_id + "." + suffix, "admin": "https://" + credential.organization_id + ".admin." + suffix, "push": "https://" + PUSH_HOSTS[credential.region]}

def _ticket(credential, authority, kind, *, value=None, token=None):
    binding = hashlib.sha256(json.dumps([credential.model_dump(), None], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if token is None:
        body = base64.urlsafe_b64encode(json.dumps({"v": 1, "scope": binding, "kind": kind, "value": value}, separators=(",", ":")).encode()).decode().rstrip("=")
        return body + "." + hmac.new(credential.api_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    try:
        if not isinstance(token, str) or len(token) > 8192: raise ValueError()
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(credential.api_key.encode(), body.encode(), hashlib.sha256).hexdigest()): raise ValueError()
        parsed = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if not isinstance(parsed, dict) or set(parsed) != {"v", "scope", "kind", "value"} or parsed["v"] != 1 or parsed["scope"] != binding or parsed["kind"] != kind or type(parsed["value"]) is not int or not 0 <= parsed["value"] <= 4999: raise ValueError()
        return parsed["value"]
    except Exception: raise ValueError("Coveo continuation does not match the credential, organization, region and query.") from None

def _privileges(raw):
    if not isinstance(raw, list) or len(raw) > 500: raise CoveoUnavailable("Coveo privilege metadata is malformed or over its bound.")
    result = []
    for row in raw:
        if not isinstance(row, dict): raise CoveoUnavailable("Coveo returned malformed privilege metadata.")
        result.append({"owner": _text(row.get("owner"), 64), "targetDomain": _text(row.get("targetDomain"), 128), "type": _text(row["type"], 64) if row.get("type") is not None else None})
    return result

def _source(raw, selected=None):
    if not isinstance(raw, dict): raise CoveoUnavailable("Coveo source metadata is malformed.")
    result = {"id": _id(raw.get("id")), "name": _text(raw.get("name")), "source_type": _text(raw.get("sourceType"), 64)}
    if selected and result["id"] != selected: raise CoveoDenied("Coveo returned a different selected organization-bound source.")
    for name in ("pushEnabled", "streamEnabled"):
        if name in raw:
            if type(raw[name]) is not bool: raise CoveoUnavailable("Coveo source flags are malformed.")
            result[name] = raw[name]
    info = raw.get("information")
    if info is not None:
        if not isinstance(info, dict): raise CoveoUnavailable("Coveo source information is malformed.")
        if info.get("sourceStatus") is not None:
            status = info["sourceStatus"]
            if not isinstance(status, dict) or status.get("type") not in STATUS_TYPES: raise CoveoUnavailable("Coveo source status is unrecognized; no completion is inferred.")
            result["status"] = {"type": status["type"], **({"activity_id": _id(status["activityId"])} if status.get("activityId") else {})}
        if "rebuildRequired" in info:
            if type(info["rebuildRequired"]) is not bool: raise CoveoUnavailable("Coveo rebuild flag is malformed.")
            result["rebuild_required"] = info["rebuildRequired"]
    return result

def _field(raw, selected=None):
    if not isinstance(raw, dict): raise CoveoUnavailable("Coveo field metadata is malformed.")
    name = raw.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", name): raise CoveoUnavailable("Coveo field name is malformed.")
    if selected and name != selected: raise CoveoDenied("Coveo returned a different selected index field.")
    if raw.get("type") not in ("STRING", "LONG", "LONG_64", "DOUBLE", "DATE"): raise CoveoUnavailable("Coveo field type is unrecognized.")
    result = {"name": name, "type": raw["type"]}
    for key in ("facet", "sort", "includeInQuery", "includeInResults"):
        if key in raw:
            if type(raw[key]) is not bool: raise CoveoUnavailable("Coveo field flags are malformed.")
            result[key] = raw[key]
    return result

class CoveoNode(WorkflowNode):
    integration_type = "automation-coveo"
    scope_registry = COVEO_SCOPES
    # Search-only keys cannot prove a human/account identity. The optional actual
    # organization probe reports its own stronger verified metadata separately.
    connection_evidence = ConnectionEvidence(noun="Coveo service", operation="test_connection", proves="reachability", label_keys=(), identity_keys=())
    edit_examples = ["Search indexed metadata in my organization", "List source refresh status", "Read current facet values", "Request a source rescan after explicit confirmation"]
    @classmethod
    def get_config_model(cls): return CoveoNodeConfig
    @classmethod
    def parse_config(cls, data):
        credential = _credential(data["credentials"]) if isinstance(data, dict) and data.get("credentials") is not None else None
        try:
            view = runtime_config_view(data, CoveoNodeConfig)
            if credential is not None: view["credentials"] = credential.model_dump()
            if isinstance(view.get("config"), dict):
                view["config"] = {key: item for key, item in view["config"].items() if not key.endswith("__label") and key not in ("_settings", "agent_tool_operations")}
                if not view["config"]: view.pop("config")
            return TypeAdapter(CoveoNodeConfig).validate_python(view)
        except Exception: raise ValueError("Check the native Coveo operation, current credential and typed fields.") from None
    @classmethod
    async def freshen_credential(cls, data, **kwargs):
        # API keys do not refresh. Saved credential access is handled by staging's loader.
        return _credential(data).model_dump()

    @classmethod
    async def _request(cls, method, service, path, *, credential, params=None, body=None, empty_ack=False):
        org = credential.organization_id
        admin = "/rest/organizations/" + org
        allowed = ((service == "search" and method == "POST" and path == "/rest/search/v2") or
            (service == "admin" and method == "GET" and (path == admin or path == admin + "/privileges/token" or re.fullmatch(re.escape(admin) + r"/(?:sources/(?:pages|[A-Za-z0-9_-]{1,256}(?:/light|/itemTypes|/schedules)?)|indexes/fields/[A-Za-z][A-Za-z0-9_]{0,127})", path))) or
            (service == "admin" and method == "POST" and (path == admin + "/indexes/fields/search" or re.fullmatch(re.escape(admin) + r"/sources/[A-Za-z0-9_-]{1,256}/(?:fullRefresh|incrementalRefresh|rebuild|pauseRefresh|resumeRefresh)", path))) or
            (service == "push" and method == "POST" and re.fullmatch(r"/push/v1/organizations/" + re.escape(org) + r"/sources/[A-Za-z0-9_-]{1,256}/status", path)))
        if not allowed: raise ValueError("Unsupported native Coveo transport path.")
        origin = _roots(credential)[service]
        assert_exact_url_origin(origin + path, origin)
        private = _PRIVATE.set(True)
        try:
            async with guarded_async_client(require_public=True, trust_env=False, follow_redirects=False, timeout=25) as client:
                async with client.stream(method, origin + path, headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json", "User-Agent": "NoClick/1.0 (+https://www.noclick.com)"}, params=params, json=body) as response:
                    if response.status_code in (401, 403): raise CoveoDenied("Coveo refused the current API key or operation permission; raw details withheld.")
                    if response.status_code != (201 if empty_ack else 200): raise CoveoUnavailable("Coveo request could not be verified, including not-visible/conflict/rate/service errors; no retry or raw response disclosure.")
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(content) + len(chunk) > MAX_JSON: raise CoveoUnavailable("Coveo exceeded its native response bound.")
                        content.extend(chunk)
                    if empty_ack:
                        if content: raise CoveoUnavailable("Coveo Push status returned an unexpected body.")
                        return None
                    mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if mime not in ("application/json", "application/problem+json"): raise CoveoUnavailable("Coveo returned an unexpected content type.")
                    payload = json.loads(content, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    if not isinstance(payload, (dict, list)) or (isinstance(payload, dict) and any(payload.get(key) not in (None, [], {}) for key in ("error", "errors", "exception"))): raise CoveoUnavailable("Coveo returned an error despite HTTP success.")
                    return payload
        except (CoveoDenied, CoveoUnavailable): raise
        except Exception: raise CoveoUnavailable("Coveo transport or response could not be verified; key, query, URLs and body details withheld.") from None
        finally: _PRIVATE.reset(private)

    async def execute(self, inputs):
        credential, config = _credential(self.config.credentials), self.config.config
        authority = None
        operation, admin = config.operation, "/rest/organizations/" + credential.organization_id
        self.scope_registry.require(operation)
        mutating = operation in LIFECYCLE or operation == "set_push_source_status"
        if mutating and not credential.allow_management_writes: raise CoveoDenied("Source management is disabled on the current saved Coveo credential.")
        if getattr(config, "include_excerpt", False) and not credential.allow_content_read: raise CoveoDenied("Indexed excerpt reads are disabled on the current saved credential.")
        calls, mutation_started, receipt_seen = 0, False, False
        async def call(method, service, path, *, params=None, body=None, empty_ack=False, mutation=False):
            nonlocal calls, mutation_started
            if calls >= 10: raise CoveoUnavailable("Coveo native request budget exceeded.")
            if credential.api_key in json.dumps([params, body]): raise ValueError("Keep Coveo key material out of query and metadata fields.")
            calls += 1
            if mutation: mutation_started = True
            return await self._request(method, service, path, credential=credential, params=params, body=body, empty_ack=empty_ack)
        def output(data):
            if credential.api_key in json.dumps(data, allow_nan=False): raise CoveoUnavailable("Coveo echoed credential material; output withheld.")
            return {"action": operation, "data": data, **({"status": "unknown"} if data.get("outcome") == "unknown" else {})}
        async def organization():
            raw = await call("GET", "admin", admin)
            if not isinstance(raw, dict) or raw.get("id") != credential.organization_id: raise CoveoDenied("Coveo returned a different actual organization.")
            result = {"organization_id": raw["id"], "organization_name": _text(raw.get("displayName"), 255)}
            if "readOnly" in raw:
                if type(raw["readOnly"]) is not bool: raise CoveoUnavailable("Coveo organization metadata is malformed.")
                result["read_only"] = raw["readOnly"]
            return result
        async def source(rid): return _source(await call("GET", "admin", admin + "/sources/" + rid), rid)
        if operation == "get_organization" or (operation == "test_connection" and credential.connection_probe == "organization"):
            found = await organization()
            if operation == "test_connection": found.update(reachable=True, authentication_verified=True, account_identity_verified=True, subject_identity_verified=None, paid_entitlement_verified=None)
            return output(found)
        if operation in ("search", "query_facets", "test_connection"):
            # GET has an optional accessToken parameter. Omit it: the current
            # Bearer token is inspected, and no secret enters a query URL.
            grants = _privileges(await call("GET", "admin", admin + "/privileges/token"))
            dangerous = {"VIEW_ALL_CONTENT", "IMPERSONATE_SEARCH_API", "VIEW_ALL", "IMPERSONATE"}
            if any(row["owner"] == "SEARCH_API" and (row["targetDomain"] in dangerous or row["type"] in dangerous) for row in grants): raise CoveoDenied("Use a permission-bound query key without Search View all content or Impersonate privileges.")
            if not any(row["owner"] == "SEARCH_API" and row["targetDomain"] == "EXECUTE_QUERY" and row["type"] in (None, "ENABLE") for row in grants): raise CoveoDenied("Current Coveo key did not expose Execute queries permission in this organization.")
            query = "" if operation == "test_connection" else config.query
            limit = config.per_page if operation == "search" else 0
            query_kind = "search:" + json.dumps(config.model_dump(exclude={"page_token"}), sort_keys=True)
            offset = _ticket(credential, authority, query_kind, token=config.page_token) if operation == "search" and config.page_token else 0
            body = {"q": query, "searchHub": credential.search_hub, "locale": getattr(config, "locale", "en-US"), "enableQuerySyntax": False, "firstResult": offset, "numberOfResults": limit, "excerptLength": 200 if getattr(config, "include_excerpt", False) else 0, "fieldsToInclude": ["source", "filetype"], "retrieveFirstSentences": False, "debug": False}
            if operation == "query_facets": body["facets"] = [{"facetId": "noclick-facet", "field": config.field_id, "type": "specific", "numberOfValues": config.number_of_values, "preventAutoSelect": True, "currentValues": [{"value": value, "state": "selected"} for value in config.selected_values]}]
            raw = await call("POST", "search", "/rest/search/v2", body=body)
            if not isinstance(raw, dict) or not isinstance(raw.get("results"), list) or len(raw["results"]) > limit: raise CoveoUnavailable("Coveo search result envelope exceeds its native bound.")
            count = _count(raw.get("totalCount"))
            if raw.get("totalCountFiltered") is not None: _count(raw["totalCountFiltered"])
            if operation == "test_connection": return output({"reachable": True, "authentication_verified": True, "account_identity_verified": False, "subject_identity_verified": None, "paid_entitlement_verified": None, "permission_bound_query_verified": True})
            if operation == "query_facets":
                facets = raw.get("facets")
                if not isinstance(facets, list) or len(facets) != 1 or not isinstance(facets[0], dict) or facets[0].get("facetId") != "noclick-facet" or facets[0].get("field") != config.field_id: raise CoveoUnavailable("Coveo facet did not match its selected field.")
                facet, values = facets[0], facets[0].get("values")
                if not isinstance(values, list) or len(values) > config.number_of_values or type(facet.get("moreValuesAvailable")) is not bool: raise CoveoUnavailable("Coveo facet values are malformed or exceed their bound.")
                parsed = []
                for value in values:
                    if not isinstance(value, dict) or value.get("state") not in ("idle", "selected", "excluded"): raise CoveoUnavailable("Coveo specific facet value is malformed.")
                    parsed.append({"value": _text(value.get("value"), 256), "state": value["state"], "number_of_results": _count(value.get("numberOfResults"))})
                return output({"field": config.field_id, "values": parsed, "more_values_available": facet["moreValuesAvailable"], "total_count_estimate": count, "snapshot_consistency_verified": None})
            results = []
            for row in raw["results"]:
                if not isinstance(row, dict): raise CoveoUnavailable("Coveo search result is malformed.")
                # The documented uniqueId can embed a private or signed URI.
                # Do not expose it: its deterministic opaque digest is only a
                # metadata reference, never a downloadable document identifier.
                uid = _text(row.get("uniqueId"), 4096)
                item = {"result_ref": hashlib.sha256(uid.encode()).hexdigest(), "title": _text(row.get("title"), 1024, empty=True)}
                if config.include_excerpt: item["excerpt"] = _text(row.get("excerpt", ""), 200, empty=True)
                results.append(item)
            if len({row["result_ref"] for row in results}) != len(results): raise CoveoUnavailable("Coveo duplicated result identifiers within its search page.")
            next_offset = offset + len(results)
            more = bool(results) and len(results) == limit and next_offset < count and next_offset <= 4999
            return output({"items": results, "first_result": offset, "total_count_estimate": count, "has_more": more, "next_page_token": _ticket(credential, authority, query_kind, value=next_offset) if more else None, "snapshot_consistency_verified": None, "document_urls_withheld": True})
        if operation in ("list_sources", "list_fields"):
            scope = "page:" + json.dumps(config.model_dump(exclude={"page_token"}), sort_keys=True)
            page = _ticket(credential, authority, scope, token=config.page_token) if config.page_token else 0
            if operation == "list_sources":
                raw = await call("GET", "admin", admin + "/sources/pages", params={"page": page, "perPage": config.per_page, "filter": config.filter, "sortingType": "NAME", "sortingOrder": "ASC"})
                key, parse = "sourceModels", _source
            else:
                raw = await call("POST", "admin", admin + "/indexes/fields/search", body={"page": page, "perPage": config.per_page, "sortBy": "name", "order": "ASC", "filters": {"name": config.filter, "facet": "TRUE_ONLY" if config.facets_only else "ALL"}})
                key, parse = "items", _field
            if not isinstance(raw, dict) or not isinstance(raw.get(key), list) or len(raw[key]) > config.per_page: raise CoveoUnavailable("Coveo returned malformed or oversized page metadata.")
            pages, entries = _count(raw.get("totalPages")), _count(raw.get("totalEntries"))
            rows = [parse(row) for row in raw[key]]
            if len({row.get("id", row.get("name")) for row in rows}) != len(rows): raise CoveoUnavailable("Coveo duplicated resource IDs in its page.")
            if pages > 5000 or entries < len(rows) or (not pages and (entries or rows)) or (pages and page >= pages) or (page + 1 < pages and not rows): raise CoveoUnavailable("Coveo page totals did not advance within the native bound.")
            more = page + 1 < pages
            return output({"items": rows, "total_entries": entries, "has_more": more, "next_page_token": _ticket(credential, authority, scope, value=page + 1) if more else None, "snapshot_consistency_verified": None})
        if operation == "get_field": return output(_field(await call("GET", "admin", admin + "/indexes/fields/" + config.field_id), config.field_id))
        found = await source(config.source_id)
        if operation == "get_source": return output(found)
        if operation == "list_source_item_types":
            raw = await call("GET", "admin", admin + "/sources/" + config.source_id + "/itemTypes")
            if not isinstance(raw, list) or len(raw) > 200: raise CoveoUnavailable("Coveo item type metadata is malformed or over its complete native bound.")
            return output({"source_id": found["id"], "items": [_text(value, 128) for value in raw]})
        if operation == "list_source_schedules":
            raw = await call("GET", "admin", admin + "/sources/" + config.source_id + "/schedules")
            if not isinstance(raw, list) or len(raw) > 200: raise CoveoUnavailable("Coveo schedule metadata is malformed or over its complete native bound.")
            rows = []
            for row in raw:
                if not isinstance(row, dict): raise CoveoUnavailable("Coveo schedule metadata is malformed.")
                if row.get("organizationId") != credential.organization_id or row.get("resourceId") != config.source_id or row.get("scheduleType") != "SOURCE": raise CoveoDenied("Coveo schedule did not match the selected organization/source.")
                if type(row.get("enabled")) is not bool or row.get("refreshType") not in ("REBUILD", "FULL_REFRESH", "INCREMENTAL_REFRESH"): raise CoveoUnavailable("Coveo source schedule flags are malformed.")
                item = {"id": _id(row.get("id")), "enabled": row["enabled"], "refresh_type": row["refreshType"], "source_id": config.source_id}
                if row.get("lastExecution") is not None: item["last_execution"] = _text(row["lastExecution"], 64)
                rows.append(item)
            return output({"source_id": found["id"], "items": rows})
        try:
            if operation in LIFECYCLE:
                receipt = _source(await call("POST", "admin", admin + "/sources/" + config.source_id + "/" + LIFECYCLE[operation], mutation=True), config.source_id)
                receipt_seen = True
                verified = await source(config.source_id)
                return output({"source": verified, "receipt": receipt, "request_accepted": True, "readback_verified": True, "requested_operation": operation, "job_completion_verified": None, "notification_delivery_verified": None})
            if operation == "set_push_source_status":
                if found["source_type"] != "PUSH" or found.get("pushEnabled") is not True: raise CoveoDenied("Select an actual Push source in this organization before setting status.")
                await call("POST", "push", "/push/v1/organizations/" + credential.organization_id + "/sources/" + config.source_id + "/status", params={"statusType": config.status_type}, empty_ack=True, mutation=True)
                receipt_seen = True
                verified = await source(config.source_id)
                return output({"source": verified, "request_accepted": True, "readback_verified": True, "requested_status": config.status_type, "requested_status_verified": None, "job_completion_verified": None, "notification_delivery_verified": None})
            raise ValueError("Unsupported native Coveo operation.")
        except Exception:
            if not mutation_started: raise
            return output({"outcome": "unknown", "source_id": config.source_id, "request_receipt_seen": receipt_seen, "readback_verified": False, "job_completion_verified": None, "retry_safe": False, "reason": "Source state may have changed; verify it before another action. No automatic retry or rollback."})

    @classmethod
    async def load_field_options(cls, field_name, user_id=None, *, credential_data=None, credential_id=None, context=None, search=None, page_token=None, **kwargs):
        if field_name not in ("source_id", "field_id"): return {"options": [], "next_page_token": None}
        context = context or {}; user_id = user_id or context.get("_user_id")
        saved = await cls.freshen_credential(credential_data, credential_id=credential_id, user_id=user_id, **kwargs)
        operation = "list_sources" if field_name == "source_id" else "list_fields"
        arguments = {"per_page": 100, "page_token": page_token, "filter": _text(search, 128, empty=True) if search else ""}
        if operation == "list_fields": arguments["facets_only"] = True
        from nodes.core.run_op import run_node_operation
        result = await run_node_operation(node_type="automation-coveo", operation=operation, arguments=arguments, credential_data=saved, credential_id=credential_id, user_id=user_id, pool=kwargs.get("pool"), organization_id=kwargs.get("organization_id"), workflow_id=kwargs.get("workflow_id"))
        if result.get("executed") is False or result.get("status") in ("pending_approval", "rejected"): return result
        page = result["data"]
        return {"options": [{"value": row.get("id", row.get("name")), "label": row["name"], "metadata": {"organization_id": _credential(saved).organization_id, "region": _credential(saved).region, "observed_page_only": True}} for row in page["items"]], "next_page_token": page["next_page_token"]}
