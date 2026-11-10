"""Native Uptime.com authenticated-user and scoped monitoring metadata reads.

Supplied keys stay in an Authorization Token header at the fixed public root.
Safe projections and fresh saved authority are retained across native seams.
"""
from dataclasses import dataclass, field
from datetime import datetime
import json
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from repositories.credentials import credential_access_predicate
from utils import credentials as credential_store
from utils.ssrf import guarded_async_client

FAMILY = "uptimecom_api_token"
NODE_TYPE = "automation-uptimecom"
ROOT = "https://uptime.com/api/v1"
OPS = ("check_connection", "list_checks", "get_check", "list_tags", "get_tag", "list_outages", "get_outage",
       "list_status_pages", "get_status_page", "get_status_page_current_status", "get_check_statistics")
CHECK_TYPES = Literal["API", "BLACKLIST", "CLOUDSTATUS", "DNS", "FTP", "SFTP", "GROUP", "HEARTBEAT", "HTTP", "ICMP", "IMAP", "MALWARE", "NTP", "PAGESPEED", "POP", "RUM2", "SMTP", "SSH", "SSL_CERT", "TCP", "TRANSACTION", "UDP", "WEBHOOK", "WHOIS", "RDAP"]
PAGE_TYPES = Literal["PUBLIC", "PUBLIC_SLA", "INTERNAL"]
VISIBILITY = Literal["UPTIME_USERS", "EXTERNAL_USERS", "PUBLIC"]
COMPONENT_STATUS = Literal["operational", "major-outage", "partial-outage", "degraded-performance", "under-maintenance"]


def resource_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,17}", value):
        raise ValueError("Enter a positive Uptime.com numeric ID without a URL, path or whitespace")
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


def approved_resources(value):
    if not isinstance(value, str) or len(value) > 15000: raise ValueError("Enter approved monitoring IDs as a JSON object")
    raw = strict_json(value)
    if not isinstance(raw, dict) or set(raw) != {"checks", "tags", "statuspages"}: raise ValueError("Use checks, tags and statuspages ID arrays")
    total = 0
    for items in raw.values():
        if not isinstance(items, list) or len(items) > 50: raise ValueError("Approve at most 50 IDs per resource family")
        ids = [resource_id(item) for item in items]
        if len(set(ids)) != len(ids): raise ValueError("Approve distinct IDs within each family")
        total += len(ids)
    if total > 100: raise ValueError("Approve at most 100 IDs in total")
    return raw


def utc_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError("Use a UTC date/time in YYYY-MM-DDTHH:MM:SSZ format")
    try: return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: raise ValueError("Use a valid UTC date/time") from None


def metadata_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
        raise ValueError("Expected a documented date-time with timezone")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: raise ValueError("Expected a valid date-time") from None
    return value


class UptimeComAPITokenCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Uptime.com API Token",
        json_schema_extra={"x-credential-instructions": "Enter an existing entitled API key, the expected numeric user pk from authenticated /auth/me/, and approved monitoring IDs. Saved restrictions narrow NoClick; provider permissions remain authoritative.", "x-help-url": "https://support.uptime.com/hc/en-us/articles/26061121898012-How-to-Connect-to-the-Uptime-com-API"})
    credential_type: Literal["uptimecom_api_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    expected_user_pk: str = Field(..., title="Expected User ID", description="Numeric pk returned by the protected /auth/me/ endpoint. This authenticates a user witness, not account ownership or paid entitlement.")
    approved_resources_json: str = Field('{"checks":[],"tags":[],"statuspages":[]}', title="Approved Monitoring IDs", description='Existing numeric IDs as JSON strings, for example {"checks":["123"],"tags":["4"],"statuspages":["5"]}. Maximum 50 per family/100 total are NoClick limits.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    include_labels: bool = Field(False, strict=True, title="Include Resource Labels", description="Opt in to check names, tag names and status-page/component names. User personal data, check configuration and all URLs are always omitted.")
    @field_validator("api_key")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value or len(value) > 4096 or value.lower().startswith(("token ", "bearer ")) or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Enter the issued key without a Token/Bearer prefix or whitespace")
        return value
    @field_validator("expected_user_pk")
    @classmethod
    def user_id_value(cls, value): return resource_id(value)
    @field_validator("approved_resources_json")
    @classmethod
    def resources(cls, value):
        approved_resources(value)
        return value


def credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != FAMILY: raise ValueError("Connect a native Uptime.com API token")
    if any(key in data for key in ("access_token", "refresh_token", "password", "api_secret", "base_url", "host", "cookie", "client_id")):
        raise ValueError("Use only the native supplied Uptime.com API-key form")
    try: return UptimeComAPITokenCredential.model_validate(data).model_dump()
    except ValueError: raise ValueError("Complete the native Uptime.com key, user witness and approved-resource form") from None


def dynamic(name, parent=None):
    spec = {"field_name": name, "searchable": True, "allow_custom": True}
    if parent: spec["depends_on"] = parent
    return {"x-resource-type": "uptimecom_" + name.removesuffix("_id"), "x-dynamic-options": spec}


class NativeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CheckConnection(NativeModel):
    operation: Literal["check_connection"] = "check_connection"


class Paged(NativeModel):
    page: int = Field(1, strict=True, ge=1, le=10000, description="Exactly one documented page per execution; no automatic traversal.")
    page_size: int = Field(25, strict=True, ge=1, le=100, description="NoClick bound; the public schema documents page_size but no server maximum.")
    search: Optional[str] = Field(None, max_length=100, description="Documented server-side search, repeated in continuation validation. Picker search is local to its current page.")


class ListChecks(Paged):
    operation: Literal["list_checks"] = "list_checks"
    monitoring_service_type: Optional[CHECK_TYPES] = None
    is_paused: Optional[bool] = Field(None, strict=True)
    state_is_up: Optional[bool] = Field(None, strict=True)


class CheckSelection(NativeModel):
    check_id: str = Field(..., title="Check", json_schema_extra=dynamic("check_id"))
    @field_validator("check_id")
    @classmethod
    def check_value(cls, value): return resource_id(value)


class GetCheck(CheckSelection):
    operation: Literal["get_check"] = "get_check"


class ListTags(Paged):
    operation: Literal["list_tags"] = "list_tags"


class GetTag(NativeModel):
    operation: Literal["get_tag"] = "get_tag"
    tag_id: str = Field(..., title="Tag", json_schema_extra=dynamic("tag_id"))
    @field_validator("tag_id")
    @classmethod
    def tag_value(cls, value): return resource_id(value)


class ListOutages(CheckSelection, Paged):
    operation: Literal["list_outages"] = "list_outages"
    ongoing: Optional[bool] = Field(None, strict=True)


class GetOutage(CheckSelection):
    operation: Literal["get_outage"] = "get_outage"
    outage_id: str = Field(..., title="Outage", json_schema_extra=dynamic("outage_id", "check_id"))
    @field_validator("outage_id")
    @classmethod
    def outage_value(cls, value): return resource_id(value)


class ListStatusPages(Paged):
    operation: Literal["list_status_pages"] = "list_status_pages"
    visibility_level: Optional[VISIBILITY] = None


class StatusPageSelection(NativeModel):
    status_page_id: str = Field(..., title="Status Page", json_schema_extra=dynamic("status_page_id"))
    @field_validator("status_page_id")
    @classmethod
    def page_value(cls, value): return resource_id(value)


class GetStatusPage(StatusPageSelection):
    operation: Literal["get_status_page"] = "get_status_page"


class GetStatusPageCurrentStatus(StatusPageSelection):
    operation: Literal["get_status_page_current_status"] = "get_status_page_current_status"


class GetCheckStatistics(CheckSelection):
    operation: Literal["get_check_statistics"] = "get_check_statistics"
    start_date: str = Field(..., description="UTC YYYY-MM-DDTHH:MM:SSZ. Native requested window is at most 31 days.")
    end_date: str = Field(..., description="UTC YYYY-MM-DDTHH:MM:SSZ, later than start_date. Returns typed date/count metadata only; opaque totals/statistic objects are omitted.")
    @field_validator("start_date", "end_date")
    @classmethod
    def date_value(cls, value):
        utc_date(value)
        return value
    @model_validator(mode="after")
    def window(self):
        delta = (utc_date(self.end_date) - utc_date(self.start_date)).total_seconds()
        if not 0 < delta <= 31 * 86400: raise ValueError("Select a positive statistics window of at most 31 days")
        return self


Operation = Annotated[Union[CheckConnection, ListChecks, GetCheck, ListTags, GetTag, ListOutages, GetOutage,
    ListStatusPages, GetStatusPage, GetStatusPageCurrentStatus, GetCheckStatistics], Field(discriminator="operation")]


class UptimeComNodeConfig(NodeConfig[Operation, UptimeComAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class Projection(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class Identified(Projection):
    pk: int = Field(ge=1, le=999999999999999999)


class UserWitness(Identified):
    is_active: bool
    is_api_enabled: bool


class Check(Identified):
    name: str = Field(max_length=100, exclude=True)
    monitoring_service_type: CHECK_TYPES
    state_is_up: bool
    is_paused: bool
    state_changed_at: str = Field(max_length=100)
    created_at: str = Field(max_length=100)
    modified_at: str = Field(max_length=100)
    @field_validator("state_changed_at", "created_at", "modified_at")
    @classmethod
    def times(cls, value): return metadata_date(value)


class Tag(Identified):
    tag: str = Field(max_length=100, exclude=True)


class Outage(Identified):
    check_pk: int = Field(ge=1)
    check_monitoring_service_type: CHECK_TYPES
    state_is_up: bool
    num_locations_down: int = Field(ge=0, le=2147483647)
    ignored: bool
    created_at: str = Field(max_length=100)
    # OAS specifies a string, without nullable/format; do not coerce to a date/number.
    resolved_at: str = Field(max_length=100, exclude=True)
    duration_secs: str = Field(max_length=100, exclude=True)
    @field_validator("created_at")
    @classmethod
    def created(cls, value): return metadata_date(value)


class StatusPage(Identified):
    name: str = Field(max_length=100, exclude=True)
    page_type: PAGE_TYPES
    visibility_level: VISIBILITY


class Component(Identified):
    name: str = Field(max_length=100, exclude=True)
    status: COMPONENT_STATUS
    service_id: Optional[int] = Field(ge=1)
    is_group: bool


class PageCurrentStatus(StatusPage):
    global_is_operational: bool
    components: list[Component] = Field(max_length=1000)
    active_incidents: list[dict] = Field(max_length=1000, exclude=True)
    upcoming_maintenance: list[dict] = Field(max_length=1000, exclude=True)
    metrics: list[dict] = Field(max_length=1000, exclude=True)


class CheckStatistics(Projection):
    # The provider SDK's documented stats response omits pk. The witnessed
    # parent and fixed request route bind the response; verify pk if supplied.
    # An explicit null is still invalid (the OpenAPI integer is not nullable).
    pk: int = Field(default=None, ge=1, le=999999999999999999)
    start_date: str = Field(max_length=100)
    end_date: str = Field(max_length=100)
    statistics: list[dict] = Field(max_length=1000, exclude=True)
    totals: dict = Field(exclude=True)
    available_locations: list = Field(max_length=1000, exclude=True)


class Listed(Projection):
    count: int = Field(ge=0)
    results: list[dict] = Field(max_length=100)
    # OAS leaves next optional. Native paging requires explicit null or a valid
    # same-route next page, so omitted continuation never proves completion.
    next: Optional[str] = Field(None, max_length=4096, exclude=True)

@dataclass(frozen=True)
class UptimeComAuthorityRow:
    credential_type: str
    owner_id: str
    token_version: int
    updated_at: datetime
    approval_revision: int
    revoked_at: Optional[datetime]
    credential: object = field(repr=False)


async def current_authority_row(pool, credential_id, principal, organization_id):
    # Keep uptimecom's revision witness local; staging owns the ACL predicate.
    async with pool.acquire() as conn:
        row = await conn.fetchrow(f"""
            SELECT c.credential_type, c.owner_id, c.token_version, c.updated_at,
                   c.approval_revision, c.revoked_at, c.credential
            FROM credentials c WHERE c.id = $1 AND {credential_access_predicate()}
        """, credential_id, principal, organization_id)
    if row is None: return None
    return UptimeComAuthorityRow(row["credential_type"], str(row["owner_id"]), row["token_version"],
        row["updated_at"], row["approval_revision"], row["revoked_at"], row["credential"])


@dataclass(frozen=True)
class Authority:
    credential_id: str
    caller_id: str
    principal_id: str
    organization_id: Optional[str]
    workflow_id: Optional[str]
    organization_derived: bool
    row: object


class BoundCredential(dict):
    def __init__(self, shaped, authority, pool):
        super().__init__(shaped)
        self["_uptimecom_authority_required"] = True
        self.authority, self.pool = authority, pool


def require_row(row):
    if row is None or row.credential_type != FAMILY or row.revoked_at is not None:
        raise ValueError("Uptime.com saved credential is unavailable")
    try: UUID(row.owner_id)
    except (TypeError, ValueError, AttributeError): raise ValueError("Uptime.com saved owner is invalid") from None
    if (type(row.token_version) is not int or row.token_version < 1
            or type(row.approval_revision) is not int or row.approval_revision < 0
            or not isinstance(row.updated_at, datetime) or row.updated_at.tzinfo is None):
        raise ValueError("Uptime.com saved authority is invalid")


async def bind_current(data, *, pool, user_id, credential_id, organization_id, workflow_id, organization_derived=False, expected=None):
    initial = credential(data)
    selected = {}
    async def load(cid, principal, current_pool, org):
        from utils.encryption import get_encryption
        row = await current_authority_row(current_pool, cid, principal, org)
        if row is None: return None
        require_row(row)
        authority = Authority(str(cid), str(user_id), str(principal), org, workflow_id, organization_derived, row)
        if expected is not None and authority != expected: raise ValueError("Uptime.com current authority changed; reload")
        try: raw = get_encryption().decrypt_credential(row.credential)
        except Exception: raise ValueError("Uptime.com saved credential could not be decrypted") from None
        now = credential({**raw, "credential_type": row.credential_type}) if isinstance(raw, dict) else None
        if now != initial: raise ValueError("Uptime.com saved key, user witness, resources or label restriction changed")
        selected["authority"] = authority
        return now
    # Use staging's authorization gates before loading a fallback principal.
    # Revision/revocation checks happen before decrypting the selected row.
    now = await load(credential_id, user_id, pool, organization_id)
    if now is None and workflow_id:
        owner = await credential_store.get_workflow_owner_id(pool, workflow_id)
        if (owner and owner != user_id and
                await credential_store.is_credential_authorized_for_workflow(pool, workflow_id, credential_id)):
            now = await load(credential_id, owner, pool, organization_id)
    if now is None and workflow_id:
        lender = await credential_store.credential_lender(pool, workflow_id, credential_id)
        if lender and lender != str(user_id):
            now = await load(credential_id, lender, pool, organization_id)
    if now is None or "authority" not in selected: raise ValueError("Uptime.com current access denied")
    return BoundCredential(now, selected["authority"], pool)


async def current_credential(data):
    now = credential(data)
    if not isinstance(data, BoundCredential):
        if "_uptimecom_authority_required" in data: raise ValueError("Uptime.com saved authority was lost; reload")
        return now
    old = data.authority
    if old.organization_derived:
        from wss.handlers.workflow_handler import get_user_org_context
        async with data.pool.acquire() as conn: org = await get_user_org_context(conn, old.caller_id)
        if org != old.organization_id: raise ValueError("Uptime.com current organization context changed; reload")
    await bind_current(data, pool=data.pool, user_id=old.caller_id, credential_id=old.credential_id,
        organization_id=old.organization_id, workflow_id=old.workflow_id, organization_derived=old.organization_derived, expected=old)
    return now


async def request(data, path, *, params=None):
    now = await current_credential(data)
    try:
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", ROOT + path, headers={"Authorization": "Token " + now["api_key"],
                "Accept": "application/json", "Content-Type": "application/json"}, params=params) as response:
                await current_credential(data)
                status = response.status_code
                if status in {400, 401, 403, 404, 422}: raise ValueError(f"Uptime.com refused the metadata read (HTTP {status})")
                if status != 200: raise RuntimeError(f"Uptime.com metadata read did not complete (HTTP {status}); no automatic retry")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json": raise RuntimeError("Uptime.com returned an unexpected response type")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000: raise RuntimeError("Uptime.com response exceeds the native metadata limit")
                await current_credential(data)
    except httpx.HTTPError: raise RuntimeError("Uptime.com metadata transport did not complete; no automatic retry") from None
    try: return strict_json(bytes(content))
    except ValueError: raise RuntimeError("Uptime.com returned invalid JSON") from None


def typed(model, raw):
    try: return model.model_validate(raw)
    except ValueError: raise RuntimeError("Uptime.com returned unverified metadata") from None


def selected_resource(now, family, value):
    value = resource_id(value)
    if value not in approved_resources(now["approved_resources_json"])[family]:
        raise ValueError("Resource is outside the saved Uptime.com approved-ID restriction")
    return value


def require_list_grant(now, family):
    if not approved_resources(now["approved_resources_json"])[family]: raise ValueError("Approve existing IDs for this Uptime.com resource family before listing")


async def user_witness(data):
    now = await current_credential(data)
    row = typed(UserWitness, await request(data, "/auth/me/"))
    if str(row.pk) != now["expected_user_pk"] or not row.is_active or not row.is_api_enabled:
        raise ValueError("Uptime.com authenticated user does not match the saved active API-user witness")
    await current_credential(data)
    return row


async def resource_witness(data, family, value):
    now = await current_credential(data)
    selected = selected_resource(now, family, value)
    model, path = {"checks": (Check, "/checks/"), "tags": (Tag, "/check-tags/"), "statuspages": (StatusPage, "/statuspages/")}[family]
    row = typed(model, await request(data, path + selected + "/"))
    if str(row.pk) != selected: raise RuntimeError("Uptime.com returned a foreign selected resource ID")
    await current_credential(data)
    return row


def output(row, now):
    result = row.model_dump()
    if now["include_labels"]:
        if isinstance(row, Tag): result["tag"] = row.tag
        elif isinstance(row, (Check, StatusPage, Component)): result["name"] = row.name
    return result


def continuation(page, cfg, path, params):
    if "next" not in page.model_fields_set: raise RuntimeError("Uptime.com omitted continuation metadata; completion is unverified")
    offset = (cfg.page - 1) * cfg.page_size
    if page.count < offset + len(page.results) or len(page.results) > cfg.page_size:
        raise RuntimeError("Uptime.com returned inconsistent list counts")
    if page.next is None:
        if page.count != offset + len(page.results): raise RuntimeError("Uptime.com final page does not reconcile with its total count")
        return None
    if not page.results: raise RuntimeError("Uptime.com returned an empty continuing page")
    if page.count <= offset + len(page.results): raise RuntimeError("Uptime.com continuation contradicts its total count")
    try:
        target = urlsplit(page.next)
        expected = urlsplit(ROOT + path)
        items = parse_qsl(target.query, keep_blank_values=True, strict_parsing=True, encoding="utf-8", errors="strict")
        query = dict(items)
        if (target.scheme != "https" or target.netloc != expected.netloc or target.path != expected.path or target.fragment
                or len(query) != len(items) or query != {**params, "page": str(cfg.page + 1)} or cfg.page >= 10000):
            raise ValueError("Unverified continuation")
    except (ValueError, UnicodeError): raise RuntimeError("Uptime.com returned an unverified next-page link; it was not followed") from None
    return cfg.page + 1


async def list_metadata(data, cfg, parent=None):
    now = await current_credential(data)
    family, path, model = {
        "list_checks": ("checks", "/checks/", Check), "list_tags": ("tags", "/check-tags/", Tag),
        "list_status_pages": ("statuspages", "/statuspages/", StatusPage), "list_outages": ("checks", "/outages/", Outage)}[cfg.operation]
    require_list_grant(now, family)
    params = {"page": str(cfg.page), "page_size": str(cfg.page_size), "ordering": "-created_at" if parent is not None else "pk"}
    if cfg.search is not None: params["search"] = cfg.search
    if isinstance(cfg, ListChecks):
        for key in ("monitoring_service_type", "is_paused", "state_is_up"):
            value = getattr(cfg, key)
            if value is not None: params[key] = str(value).lower() if isinstance(value, bool) else value
    if isinstance(cfg, ListStatusPages) and cfg.visibility_level is not None: params["visibility_level"] = cfg.visibility_level
    if parent is not None:
        params["check_pk"] = str(parent.pk)
        if cfg.ongoing is not None: params["ongoing"] = str(cfg.ongoing).lower()
    listed = typed(Listed, await request(data, path, params=params))
    next_page = continuation(listed, cfg, path, params)
    rows, seen = [], set()
    allowed = approved_resources(now["approved_resources_json"])[family]
    for raw in listed.results:
        row = typed(model, raw)
        if row.pk in seen: raise RuntimeError("Uptime.com returned repeated resource IDs")
        seen.add(row.pk)
        if parent is not None:
            if row.check_pk != parent.pk: raise RuntimeError("Uptime.com outage does not belong to the witnessed check")
            rows.append(output(row, now))
        elif str(row.pk) in allowed: rows.append(output(row, now))
    await current_credential(data)
    return {"status": "success", "results": rows, "count": listed.count, "returned_count": len(rows),
        "filtered_count": len(listed.results) - len(rows), "has_more": next_page is not None, "next_page": next_page,
        "pages_read": 1, "complete_from_first_page": cfg.page == 1 and next_page is None,
        "identity_verified": True, "account_ownership_verified": False,
        **({"check_pk": parent.pk, "parent_link_verified": True} if parent is not None else {})}


def current_status_output(row, now):
    checks = approved_resources(now["approved_resources_json"])["checks"]
    components, seen = [], set()
    for item in row.components:
        if item.pk in seen: raise RuntimeError("Uptime.com repeated a status-page component ID")
        seen.add(item.pk)
        if item.service_id is None or str(item.service_id) in checks: components.append(output(item, now))
    result = {"pk": row.pk, "page_type": row.page_type, "visibility_level": row.visibility_level,
        "global_is_operational": row.global_is_operational, "components": components,
        "filtered_component_count": len(row.components) - len(components), "active_incident_count": len(row.active_incidents),
        "upcoming_maintenance_count": len(row.upcoming_maintenance), "metric_count": len(row.metrics)}
    if now["include_labels"]: result["name"] = row.name
    return result


def response_date(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None: raise ValueError("Missing timezone")
        return result
    except ValueError: raise RuntimeError("Uptime.com returned an unverified statistics date/time") from None


class UptimeComNode(WorkflowNode):
    integration_type = "automation-uptimecom"
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(identity_operation="check_connection", noun="Uptime.com authenticated user ID",
        label_keys=(), identity_keys=("user_pk",), proves="account")
    scope_registry = ScopeRegistry(provider="uptimecom", enforcement=Enforcement.STRICT,
        requirements={op: ScopeRequirement(scopes=(), credential_types=(FAMILY,),
            note="Supplied Token-header API family. No OAuth scope names are invented; actual current access, saved restrictions and provider API permissions remain authoritative.") for op in OPS})
    edit_examples = ["Read cached status for an approved monitoring check", "List outages for one approved check", "Read current status for an approved status page"]
    @classmethod
    def get_config_model(cls): return UptimeComNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None: credential(config_data["credentials"])
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: credential(config_data["credentials"])
            except ValueError: return {"valid": False, "errors": ["Complete the native Uptime.com credential form"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        data = credential_data
        credential(data)
        if isinstance(data, BoundCredential):
            await current_credential(data)
            return data
        if "_uptimecom_authority_required" in data: raise ValueError("Uptime.com saved authority was lost; reload")
        if not credential_id: return credential(data)
        if not user_id: raise ValueError("Uptime.com requires the actual current caller")
        if pool is None:
            from utils.database_pool import get_native_pool
            pool = get_native_pool()
        from wss.handlers.workflow_handler import get_user_org_context
        async with pool.acquire() as conn: organization_id = await get_user_org_context(conn, user_id)
        return await bind_current(data, pool=pool, user_id=user_id, credential_id=credential_id,
            organization_id=organization_id, workflow_id=None, organization_derived=True)
    @classmethod
    async def validate_credential_access(cls, data):
        # Staging passes the decrypted accessible credential to this hook.
        try:
            await user_witness(data)
        except ValueError: return {"valid": False, "error": "Uptime.com refused current API-user access"}
        except Exception: return {"valid": None, "error": "Uptime.com API-user access could not be judged"}
        return {"valid": True, "proves": "account", "identity_verified": True, "account_ownership_verified": False}
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        context = context if isinstance(context, dict) else {}
        now = await current_credential(credential_data)
        if page_token is not None and (not isinstance(page_token, str) or not re.fullmatch(r"[1-9][0-9]{0,4}", page_token) or int(page_token) > 10000):
            raise ValueError("Use a native Uptime.com page number")
        page = int(page_token) if page_token is not None else 1
        family = {"check_id": "checks", "tag_id": "tags", "status_page_id": "statuspages", "outage_id": "checks"}.get(field_name)
        if family is None: return {"options": [], "has_more": False, "next_page_token": None}
        require_list_grant(now, family)
        if field_name == "outage_id": selected_resource(now, "checks", context.get("check_id"))
        await user_witness(credential_data)
        if field_name == "outage_id":
            parent = await resource_witness(credential_data, "checks", context.get("check_id"))
            result = await list_metadata(credential_data, ListOutages(check_id=str(parent.pk), page=page), parent)
        else:
            model = {"check_id": ListChecks, "tag_id": ListTags, "status_page_id": ListStatusPages}[field_name]
            result = await list_metadata(credential_data, model(page=page))
        options = [{"value": str(row["pk"]), "label": row.get("name") or row.get("tag") or str(row["pk"])} for row in result["results"]]
        term = (normalize_search(search) or "").casefold()
        if term: options = [row for row in options if term in (row["label"] + " " + row["value"]).casefold()]
        await current_credential(credential_data)
        return {"options": options, "has_more": result["has_more"], "next_page_token": str(result["next_page"]) if result["next_page"] is not None else None}
    async def execute(self, inputs: dict) -> dict:
        # Preserve bound saved authority when present; direct native execution
        # also accepts the credential already validated in the parsed config.
        supplied = self.node_data.get("credentials")
        if supplied is None and self.config.credentials is not None:
            supplied = self.config.credentials.model_dump()
        data = await self.freshen_credential(supplied, pool=self.node_data.get("_approval_pool"),
            user_id=self.user_id, credential_id=self.node_data.get("credential_id"))
        cfg = self.config.config
        now = await current_credential(data)
        if isinstance(cfg, (ListChecks, ListTags, ListStatusPages)):
            require_list_grant(now, {"list_checks": "checks", "list_tags": "tags", "list_status_pages": "statuspages"}[cfg.operation])
        elif isinstance(cfg, CheckSelection): selected_resource(now, "checks", cfg.check_id)
        elif isinstance(cfg, GetTag): selected_resource(now, "tags", cfg.tag_id)
        elif isinstance(cfg, StatusPageSelection): selected_resource(now, "statuspages", cfg.status_page_id)
        user = await user_witness(data)
        if isinstance(cfg, CheckConnection):
            return {"status": "success", "user_pk": user.pk, "is_active": user.is_active, "is_api_enabled": user.is_api_enabled,
                "identity_verified": True, "account_ownership_verified": False}
        if isinstance(cfg, (ListChecks, ListTags, ListStatusPages)): return await list_metadata(data, cfg)
        family, selected = ("checks", cfg.check_id) if isinstance(cfg, CheckSelection) else ("tags", cfg.tag_id) if isinstance(cfg, GetTag) else ("statuspages", cfg.status_page_id)
        parent = await resource_witness(data, family, selected)
        if isinstance(cfg, (GetCheck, GetTag, GetStatusPage)):
            return {"status": "success", "data": output(parent, now), "identity_verified": True, "account_ownership_verified": False}
        if isinstance(cfg, ListOutages): return await list_metadata(data, cfg, parent)
        if isinstance(cfg, GetOutage):
            row = typed(Outage, await request(data, "/outages/" + cfg.outage_id + "/"))
            if str(row.pk) != cfg.outage_id or row.check_pk != parent.pk: raise RuntimeError("Uptime.com outage does not match its selected ID/check parent")
            await current_credential(data)
            return {"status": "success", "data": output(row, now), "parent_link_verified": True, "identity_verified": True, "account_ownership_verified": False}
        if isinstance(cfg, GetStatusPageCurrentStatus):
            row = typed(PageCurrentStatus, await request(data, "/statuspages/" + selected + "/current-status/"))
            if row.pk != parent.pk: raise RuntimeError("Uptime.com current status does not match its selected page")
            await current_credential(data)
            return {"status": "success", "data": current_status_output(row, now), "parent_route_verified": True, "identity_verified": True, "account_ownership_verified": False}
        if isinstance(cfg, GetCheckStatistics):
            row = typed(CheckStatistics, await request(data, "/checks/" + selected + "/stats/", params={"start_date": cfg.start_date,
                "end_date": cfg.end_date, "include_alerts": "false", "locations_response_times": "false", "download": "false", "pdf": "false"}))
            if (("pk" in row.model_fields_set and row.pk != parent.pk) or response_date(row.start_date) != utc_date(cfg.start_date) or response_date(row.end_date) != utc_date(cfg.end_date)):
                raise RuntimeError("Uptime.com statistics do not match the selected check/date window")
            await current_credential(data)
            return {"status": "success", "check_pk": parent.pk, "start_date": row.start_date, "end_date": row.end_date,
                "statistic_record_count": len(row.statistics), "available_location_count": len(row.available_locations),
                "totals_present": bool(row.totals), "opaque_values_omitted": True, "parent_route_verified": True,
                "identity_verified": True, "account_ownership_verified": False}
        raise ValueError("Use a native Uptime.com monitoring metadata read")
