"""PredictLeads subscription and company-signal reads on the documented v3 API.

The supplied header pair retains current saved-row authority. Dataset requests
consume credits; projected results exclude recruiter/contact and article bodies.
"""
from dataclasses import dataclass
from datetime import date, datetime
import json
import math
import re
from typing import Annotated, Literal, Optional, Union
from uuid import UUID
from types import SimpleNamespace

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from repositories.credentials import credential_access_predicate
from utils import credentials as credential_utils
from utils.ssrf import guarded_async_client

FAMILY = "predictleads_api_key_token"
NODE_TYPE = "automation-predictleads"
ROOT = "https://predictleads.com/api/v3"
JOB_CATEGORIES = set("administration consulting data_analysis design directors education engineering finance healthcare_services human_resources information_technology internship legal management marketing military_and_protective_services operations purchasing product_management quality_assurance real_estate research sales software_development support manual_work food".split())
NEWS_CATEGORIES = set("acquires merges_with sells_assets_to loses_client signs_new_client declares_bankruptcy files_suit_against has_issues_with closes_offices_in decreases_headcount_by attends_event expands_facilities expands_offices_in expands_offices_to increases_headcount_by opens_new_location goes_public has_earnings has_revenue has_valuation invests_into invests_into_assets receives_financing hires leaves promotes retires_from integrates_with is_developing launches ends_partnership_with partners_with receives_award recognized_as identified_as_competitor_of spins_off_company spins_off_division".split())
OPS = ("check_connection", "get_company", "list_job_openings", "list_news_events", "list_technology_detections")


def company_selector(value):
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("Enter a company UUID or bare domain")
    try:
        return str(UUID(value))
    except ValueError:
        pass
    value = value.lower()
    if len(value) > 253 or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
        raise ValueError("Enter a company UUID or bare domain without a path, port or URL prefix")
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


def granted_companies(value):
    if not isinstance(value, str) or len(value) > 20000:
        raise ValueError("Use a JSON string array of approved company UUIDs or domains")
    raw = strict_json(value)
    if not isinstance(raw, list) or not 1 <= len(raw) <= 50:
        raise ValueError("Approve between one and 50 companies")
    result = [company_selector(item) for item in raw]
    if len(set(result)) != len(result): raise ValueError("Approve distinct company selectors")
    return result


def date_input(value):
    if value is None or type(value) is date: return value
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Use an ISO date in YYYY-MM-DD format")
    return date.fromisoformat(value)


class PredictLeadsAPIKeyTokenCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="PredictLeads API Key and Token",
        json_schema_extra={"x-credential-instructions": "Enter the supplied key and token. Subscription checks use no credits; company and signal reads consume credits. Approved companies are a local workflow restriction, not vendor OAuth scopes.",
                           "x-help-url": "https://docs.predictleads.com/swagger"})
    credential_type: Literal["predictleads_api_key_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    api_token: str = Field(..., title="API Token", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    allowed_companies_json: str = Field(..., title="Approved Companies", description="JSON string array of company UUIDs or bare domains. The picker uses this saved list without spending credits. Maximum 50 is a NoClick limit.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    allow_credit_reads: bool = Field(False, strict=True, title="Allow Credit-Consuming Reads", description="Permit this node to request company and signal datasets. Each company witness and dataset page costs one credit according to the current API spec.")
    @field_validator("api_key", "api_token")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="API credential")
        if len(value) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Enter the issued credential without a header prefix or whitespace")
        return value
    @field_validator("allowed_companies_json")
    @classmethod
    def companies(cls, value):
        granted_companies(value)
        return value


# PredictLeads's own MCP server: agents get its tools through a person's PredictLeads sign-in.
PredictleadsMcpCredential = mcp_credential("predictleads", "https://mcp.predictleads.com/", app="PredictLeads")
PredictLeadsTokenCredential = Union[PredictLeadsAPIKeyTokenCredential, PredictleadsMcpCredential]


def credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != FAMILY:
        raise ValueError("Connect a native PredictLeads API key and token")
    if any(key in data for key in ("access_token", "refresh_token", "base_url", "host", "authorization")):
        raise ValueError("Use only the native PredictLeads header-key form")
    try: return PredictLeadsAPIKeyTokenCredential.model_validate(data).model_dump()
    except ValueError: raise ValueError("Complete the native PredictLeads key, token and company form") from None


class NativeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CheckConnection(NativeModel):
    operation: Literal["check_connection"] = "check_connection"


class CompanySelection(NativeModel):
    company: str = Field(..., title="Company UUID or Domain", description="Choose an approved company. Executing this read consumes credits.", json_schema_extra={"x-resource-type": "predictleads_company", "x-dynamic-options": {"field_name": "company", "searchable": True, "allow_custom": True}})
    @field_validator("company")
    @classmethod
    def selector(cls, value): return company_selector(value)


class GetCompany(CompanySelection):
    operation: Literal["get_company"] = "get_company"


class PagedCompany(CompanySelection):
    page: int = Field(1, strict=True, ge=1, le=100000, title="Starting Page")
    limit: int = Field(100, strict=True, ge=1, le=1000, title="Page Size", description="Vendor maximum 1,000 records per page.")
    max_pages: int = Field(1, strict=True, ge=1, le=5, title="Maximum Pages", description="NoClick bound. Each page consumes one credit, plus one company-witness credit.")


class SeenDates(PagedCompany):
    first_seen_at_from: Optional[date] = None
    first_seen_at_until: Optional[date] = None
    last_seen_at_from: Optional[date] = None
    last_seen_at_until: Optional[date] = None
    @field_validator("first_seen_at_from", "first_seen_at_until", "last_seen_at_from", "last_seen_at_until", mode="before")
    @classmethod
    def dates(cls, value): return date_input(value)
    @model_validator(mode="after")
    def ranges(self):
        for prefix in ("first_seen_at", "last_seen_at"):
            start, end = getattr(self, prefix + "_from"), getattr(self, prefix + "_until")
            if start and end and start > end: raise ValueError("The beginning of a date range must precede its end")
        return self


class ListJobOpenings(SeenDates):
    operation: Literal["list_job_openings"] = "list_job_openings"
    active_only: Optional[bool] = Field(None, strict=True)
    not_closed: Optional[bool] = Field(None, strict=True)
    with_description_only: Optional[bool] = Field(None, strict=True)
    with_location_only: Optional[bool] = Field(None, strict=True)
    location: Optional[str] = Field(None, max_length=200)
    categories: list[str] = Field(default_factory=list, max_length=28, json_schema_extra={"ui:widget": "list"})
    @field_validator("categories")
    @classmethod
    def categories_valid(cls, value):
        if len(set(value)) != len(value) or not set(value) <= JOB_CATEGORIES: raise ValueError("Select documented distinct job categories")
        return value


class ListNewsEvents(PagedCompany):
    operation: Literal["list_news_events"] = "list_news_events"
    found_at_from: Optional[date] = None
    found_at_until: Optional[date] = None
    location: Optional[str] = Field(None, max_length=200)
    categories: list[str] = Field(default_factory=list, max_length=37, json_schema_extra={"ui:widget": "list"})
    @field_validator("found_at_from", "found_at_until", mode="before")
    @classmethod
    def dates(cls, value): return date_input(value)
    @field_validator("categories")
    @classmethod
    def categories_valid(cls, value):
        if len(set(value)) != len(value) or not set(value) <= NEWS_CATEGORIES: raise ValueError("Select documented distinct news categories")
        return value
    @model_validator(mode="after")
    def ranges(self):
        if self.found_at_from and self.found_at_until and self.found_at_from > self.found_at_until:
            raise ValueError("The beginning of a date range must precede its end")
        return self


class ListTechnologyDetections(SeenDates):
    operation: Literal["list_technology_detections"] = "list_technology_detections"


Operation = Annotated[Union[CheckConnection, GetCompany, ListJobOpenings, ListNewsEvents, ListTechnologyDetections], Field(discriminator="operation")]


class PredictLeadsNodeConfig(NodeConfig[Operation, PredictLeadsTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class Projection(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)
    @field_validator("*", mode="after")
    @classmethod
    def documented_dates(cls, value, info):
        if value is not None and info.field_name in {"first_seen_at", "last_seen_at", "found_at"}:
            if not isinstance(value, str) or len(value) > 100 or datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                raise ValueError("Use a documented ISO timestamp")
        if value is not None and info.field_name == "effective_date": date.fromisoformat(value)
        return value


class Reference(Projection):
    id: str
    type: str
    @field_validator("id")
    @classmethod
    def uuid_id(cls, value):
        return str(UUID(value))


class Relationship(Projection):
    data: Union[Reference, list[Reference], None]


class Resource(Reference):
    attributes: dict
    relationships: dict[str, Relationship] = Field(default_factory=dict)


class CompanyAttributes(Projection):
    domain: str
    company_name: Optional[str]
    ticker: Optional[str]
    friendly_company_name: Optional[str] = None
    language: Optional[str] = None
    location: Optional[str] = None
    @field_validator("domain")
    @classmethod
    def domain_valid(cls, value):
        selector = company_selector(value)
        if "." not in selector: raise ValueError("Use the documented company domain")
        return selector


class JobAttributes(Projection):
    normalized_title: Optional[str]
    translated_title: Optional[str]
    url: str
    first_seen_at: str
    last_seen_at: str
    status: Optional[Literal["closed"]]
    categories: list[str]
    language: Optional[str]
    location: Optional[str]
    @field_validator("categories")
    @classmethod
    def categories_valid(cls, value):
        if not set(value) <= JOB_CATEGORIES: raise ValueError("Undocumented job categories")
        return value


class NewsAttributes(Projection):
    category: str
    found_at: str
    first_seen_at: str
    confidence: float = Field(ge=0, le=1)
    planning: bool
    effective_date: Optional[str] = None
    location: Optional[str] = None
    @field_validator("category")
    @classmethod
    def category_valid(cls, value):
        if value not in NEWS_CATEGORIES: raise ValueError("Undocumented news category")
        return value


class TechnologyAttributes(Projection):
    first_seen_at: str
    last_seen_at: str
    behind_firewall: bool
    score: float
    source_count: int = Field(ge=0)
    department_onet_codes: list[str]
    @field_validator("score")
    @classmethod
    def finite_score(cls, value):
        if not math.isfinite(value): raise ValueError("Use a finite score")
        return value


class TechnologyName(Projection):
    name: str


class SubscriptionAttributes(Projection):
    status: Literal["disabled", "active", "disabled_due_to_error"]
    monthly_credits_quota: int = Field(ge=0)
    monthly_credits_used: int = Field(ge=0)


class Dataset(Projection):
    data: list[Resource]
    included: list[Resource]
    meta: dict = Field(default_factory=dict)


class Subscription(Projection):
    data: list[Resource]
    meta: dict = Field(default_factory=dict)


@dataclass(frozen=True)
class Authority:
    credential_id: str
    caller_id: str
    principal_id: str
    organization_id: Optional[str]
    workflow_id: Optional[str]
    row: object


class BoundCredential(dict):
    def __init__(self, shaped, authority, pool):
        super().__init__(shaped)
        self["_predictleads_authority_required"] = True
        self.authority, self.pool = authority, pool


def require_row(row):
    if row is None or row.credential_type != FAMILY or row.revoked_at is not None:
        raise ValueError("PredictLeads saved credential is unavailable")
    try: UUID(row.owner_id)
    except (TypeError, ValueError, AttributeError):
        raise ValueError("PredictLeads saved owner is invalid") from None
    if (type(row.token_version) is not int or row.token_version < 1
            or type(row.approval_revision) is not int or row.approval_revision < 0
            or not isinstance(row.updated_at, datetime) or row.updated_at.tzinfo is None):
        raise ValueError("PredictLeads saved authority is invalid")


async def bind_current(data, *, pool, user_id, credential_id, organization_id, workflow_id, expected=None):
    initial = credential(data)
    selected = {}
    async def load(cid, principal, current_pool, org):
        from utils.encryption import get_encryption
        # Keep the saved-row snapshot local; staging exposes the canonical ACL
        # predicate and workflow authorization helpers, not a validation loader.
        async with current_pool.acquire() as conn:
            record = await conn.fetchrow(f"""
                SELECT c.credential_type, c.credential, c.owner_id::text AS owner_id,
                       c.token_version, c.approval_revision, c.updated_at, c.revoked_at
                FROM credentials c WHERE c.id = $1 AND {credential_access_predicate()}
            """, cid, principal, org)
        row = SimpleNamespace(**dict(record)) if record is not None else None
        if row is None: return None
        require_row(row)
        authority = Authority(str(cid), str(user_id), str(principal), org, workflow_id, row)
        if expected is not None and authority != expected:
            raise ValueError("PredictLeads current authority changed; reload")
        try: raw = get_encryption().decrypt_credential(row.credential)
        except Exception:
            raise ValueError("PredictLeads saved credential could not be decrypted") from None
        now = credential({**raw, "credential_type": row.credential_type}) if isinstance(raw, dict) else None
        if now != initial:
            raise ValueError("PredictLeads saved key, token or grants changed")
        selected["authority"] = authority
        return now
    now = await load(credential_id, user_id, pool, organization_id)
    if now is None and workflow_id:
        owner = await credential_utils.get_workflow_owner_id(pool, workflow_id)
        if (owner and owner != user_id
                and await credential_utils.is_credential_authorized_for_workflow(pool, workflow_id, credential_id)):
            now = await load(credential_id, owner, pool, organization_id)
    if now is None and workflow_id:
        lender = await credential_utils.credential_lender(pool, workflow_id, credential_id)
        if lender and lender != str(user_id):
            now = await load(credential_id, lender, pool, organization_id)
    if now is None or "authority" not in selected:
        raise ValueError("PredictLeads current access denied")
    return BoundCredential(now, selected["authority"], pool)


async def current_credential(data):
    now = credential(data)
    if not isinstance(data, BoundCredential):
        if "_predictleads_authority_required" in data:
            raise ValueError("PredictLeads saved authority was lost; reload")
        return now
    old = data.authority
    await bind_current(data, pool=data.pool, user_id=old.caller_id, credential_id=old.credential_id,
        organization_id=old.organization_id, workflow_id=old.workflow_id, expected=old)
    return now


async def request(data, path, params=None):
    now = await current_credential(data)
    try:
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", ROOT + path, headers={"X-Api-Key": now["api_key"], "X-Api-Token": now["api_token"], "Accept": "application/json"}, params=params) as response:
                await current_credential(data)
                status = response.status_code
                if status in {400, 401, 402, 403, 404, 422}:
                    reason = {402: "monthly credit quota exceeded", 403: "request rate limit exceeded"}.get(status, "read refused")
                    raise ValueError(f"PredictLeads {reason} (HTTP {status})")
                if status == 429:
                    raw = response.headers.get("retry-after", "")
                    delay = int(raw) if raw.isascii() and raw.isdigit() and len(raw) <= 8 else None
                    suffix = f"; retry after {delay} seconds" if delay is not None else ""
                    raise RuntimeError("PredictLeads too many requests (HTTP 429)" + suffix + "; no automatic retry")
                if status != 200: raise RuntimeError(f"PredictLeads read did not complete (HTTP {status}); no automatic retry")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise RuntimeError("PredictLeads returned an unexpected response type")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000: raise RuntimeError("PredictLeads response exceeds the native read limit")
                await current_credential(data)
    except httpx.HTTPError: raise RuntimeError("PredictLeads transport did not complete; no automatic retry") from None
    try: return strict_json(bytes(content))
    except ValueError: raise RuntimeError("PredictLeads returned invalid JSON") from None


def resources(raw, kind):
    try:
        envelope = Dataset.model_validate(raw)
        if any("relationships" not in row for row in raw["data"]): raise ValueError("Required relationships missing")
        if len(envelope.data) > 1000 or len(envelope.included) > 10000: raise ValueError("Unbounded dataset")
        seen = set()
        for row in envelope.data:
            if row.type != kind or row.id in seen: raise ValueError("Unexpected resource type or repeated ID")
            seen.add(row.id)
        included_seen = set()
        for row in envelope.included:
            if (row.type, row.id) in included_seen: raise ValueError("Repeated included resource")
            included_seen.add((row.type, row.id))
        return envelope
    except (ValueError, TypeError): raise RuntimeError("PredictLeads returned an unverified JSON:API dataset") from None


async def check_subscription(data):
    raw = await request(data, "/api_subscription")
    try:
        envelope = Subscription.model_validate(raw)
        if len(envelope.data) != 1 or envelope.data[0].type != "api_subscription": raise ValueError("Unverified subscription witness")
        row = envelope.data[0]
        attrs = SubscriptionAttributes.model_validate(row.attributes).model_dump()
    except (ValueError, TypeError): raise RuntimeError("PredictLeads did not return a typed subscription witness") from None
    if attrs["status"] != "active": raise ValueError("PredictLeads subscription is not active")
    await current_credential(data)
    return {"status": "success", "witness_verified": True, "identity_verified": False,
        "data": [{"id": row.id, "type": row.type, "attributes": attrs}], "documented_credits": 0}


async def company_witness(data, selector):
    now = await current_credential(data)
    selector = company_selector(selector)
    if selector not in granted_companies(now["allowed_companies_json"]):
        raise ValueError("Company is outside the saved approved-company list")
    if now["allow_credit_reads"] is not True: raise ValueError("Enable credit-consuming reads in the saved credential")
    envelope = resources(await request(data, "/companies/" + selector), "company")
    if len(envelope.data) != 1: raise RuntimeError("PredictLeads did not return the requested company witness")
    row = envelope.data[0]
    try: attrs = CompanyAttributes.model_validate(row.attributes).model_dump(exclude_unset=True)
    except ValueError: raise RuntimeError("PredictLeads returned unverified company attributes") from None
    if selector != row.id and selector != attrs["domain"]:
        raise RuntimeError("PredictLeads company does not match the selected UUID or domain; redirects are not followed")
    await current_credential(data)
    return {"id": row.id, "type": row.type, "attributes": attrs}


def query_filters(cfg):
    values = cfg.model_dump(exclude_none=True)
    for name in ("operation", "company", "max_pages"): values.pop(name, None)
    return {key: (",".join(value) if isinstance(value, list) else value.isoformat() if isinstance(value, date) else "true" if value is True else "false" if value is False else value)
        for key, value in values.items() if not isinstance(value, list) or value}


def projected_record(row, company_id, included, kind):
    models = {"job_opening": JobAttributes, "news_event": NewsAttributes, "technology_detection": TechnologyAttributes}
    attrs = models[kind].model_validate(row.attributes).model_dump(exclude_unset=True)
    keys = ("company1", "company2") if kind == "news_event" else ("company",)
    refs = []
    relations = {}
    for key in keys:
        rel = row.relationships.get(key)
        if rel is None:
            if kind != "news_event": raise ValueError("Required company relationship missing")
            continue
        if not isinstance(rel.data, Reference) or rel.data.type != "company": raise ValueError("Invalid company relationship")
        refs.append(rel.data.id)
        relations[key] = {"data": rel.data.model_dump()}
    if refs and company_id not in refs: raise ValueError("Foreign company relationship")
    if kind == "technology_detection":
        rel = row.relationships.get("technology")
        if rel is None or not isinstance(rel.data, Reference) or rel.data.type != "technology": raise ValueError("Missing technology relationship")
        relations["technology"] = {"data": rel.data.model_dump()}
        matches = [item for item in included if item.type == "technology" and item.id == rel.data.id]
        if len(matches) != 1: raise ValueError("Missing referenced technology")
        name = TechnologyName.model_validate(matches[0].attributes).model_dump()
        technology = {"id": rel.data.id, "type": "technology", "attributes": name}
    else: technology = None
    return {"id": row.id, "type": row.type, "attributes": attrs, "relationships": relations,
            "company_link_verified": bool(refs)}, technology


async def list_signals(data, cfg):
    witness = await company_witness(data, cfg.company)
    path, kind = {"list_job_openings": ("job_openings", "job_opening"), "list_news_events": ("news_events", "news_event"),
                  "list_technology_detections": ("technology_detections", "technology_detection")}[cfg.operation]
    filters = query_filters(cfg)
    rows, technologies, seen = [], {}, set()
    count = None
    offset = (cfg.page - 1) * cfg.limit
    for index in range(cfg.max_pages):
        page = cfg.page + index
        params = {**filters, "page": page}
        envelope = resources(await request(data, "/companies/" + cfg.company + "/" + path, params), kind)
        current_count = envelope.meta.get("count")
        if (type(current_count) is not int or current_count < 0 or (count is not None and current_count != count)
                or envelope.meta.get("record_state") != "active"
                or not isinstance(envelope.meta.get("schema_version"), str) or not envelope.meta["schema_version"]):
            raise RuntimeError("PredictLeads did not return a stable documented page count; completion is unverified")
        count = current_count
        if len(envelope.data) > cfg.limit or offset + len(rows) + len(envelope.data) > max(count, offset):
            raise RuntimeError("PredictLeads page length disagrees with its count")
        for row in envelope.data:
            if row.id in seen: raise RuntimeError("PredictLeads repeated a resource across pages; completion is unverified")
            seen.add(row.id)
            try: projected, technology = projected_record(row, witness["id"], envelope.included, kind)
            except ValueError: raise RuntimeError("PredictLeads returned unverified signal attributes or company linkage") from None
            rows.append(projected)
            if technology: technologies[technology["id"]] = technology
        has_more = offset + len(rows) < count
        if not has_more: break
        if len(envelope.data) != cfg.limit:
            raise RuntimeError("PredictLeads returned a short or empty page before its count; completion is unverified")
    await current_credential(data)
    return {"status": "success", "company": witness, "data": rows, "included": list(technologies.values()),
        "meta": {"count": count, "start_page": cfg.page, "pages_read": index + 1, "has_more": has_more,
                 "next_page": page + 1 if has_more else None, "complete_from_first_page": cfg.page == 1 and not has_more},
        "documented_credits": index + 2, "identity_verified": False,
        "unresolved_company_link_count": sum(not row["company_link_verified"] for row in rows)}


class PredictLeadsNode(WorkflowNode):
    integration_type = "automation-predictleads"
    credential_provider_labels = {"predictleads": "PredictLeads Account"}
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="PredictLeads subscription",
        label_keys=("id",), identity_keys=(), proves="reachability")
    scope_registry = ScopeRegistry(provider="predictleads", enforcement=Enforcement.STRICT,
        requirements={op: ScopeRequirement(scopes=(), credential_types=(FAMILY,),
            note="This node uses supplied header keys; approved companies and credit permission are local restrictions, not OAuth scopes.") for op in OPS})
    edit_examples = ["Read active job openings for an approved company", "Read company news and detected technologies with a bounded credit cost"]
    @classmethod
    def get_config_model(cls): return PredictLeadsNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None: credential(config_data["credentials"])
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: credential(config_data["credentials"])
            except ValueError: return {"valid": False, "errors": ["Complete the native PredictLeads credential form"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._freshen_current_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
    @classmethod
    async def _freshen_current_credential(cls, data, *, pool=None, user_id=None, credential_id=None, organization_id=None, workflow_id=None):
        credential(data)
        if isinstance(data, BoundCredential):
            await current_credential(data)
            return data
        if "_predictleads_authority_required" in data: raise ValueError("PredictLeads saved authority was lost; reload")
        if not credential_id: return credential(data)
        if not user_id: raise ValueError("PredictLeads requires the actual current caller")
        if pool is None:
            from utils.database_pool import get_native_pool
            pool = get_native_pool()
        return await bind_current(data, pool=pool, user_id=user_id, credential_id=credential_id,
            organization_id=organization_id, workflow_id=workflow_id)
    @classmethod
    async def validate_credential_access(cls, data):
        # Staging calls the hook with the accessible, decrypted credential only.
        try:
            result = await check_subscription(credential(data))
        except ValueError:
            return {"valid": False, "error": "PredictLeads refused current subscription access"}
        except Exception:
            return {"valid": None, "error": "PredictLeads subscription access could not be judged"}
        if result.get("witness_verified") is not True:
            return {"valid": None, "error": "PredictLeads did not verify the subscription witness"}
        return {"valid": True, "proves": "reachability", "identity_verified": False}
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name != "company": return {"options": [], "has_more": False, "next_page_token": None}
        if page_token: raise ValueError("The saved PredictLeads company picker has no paging cursor")
        now = await current_credential(credential_data)
        term = (normalize_search(search) or "").casefold()
        options = [{"value": item, "label": item} for item in granted_companies(now["allowed_companies_json"]) if term in item.casefold()]
        await current_credential(credential_data)
        return {"options": options, "has_more": False, "next_page_token": None}
    async def execute(self, inputs: dict) -> dict:
        supplied = self.node_data.get("credentials")
        if "credentials" not in self.node_data and self.config.credentials is not None:
            supplied = self.config.credentials.model_dump()
        data = await self._freshen_current_credential(supplied, pool=self.node_data.get("_approval_pool"),
            user_id=self.user_id, credential_id=self.node_data.get("credential_id"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        cfg = self.config.config
        if isinstance(cfg, CheckConnection): return await check_subscription(data)
        if isinstance(cfg, GetCompany):
            row = await company_witness(data, cfg.company)
            return {"status": "success", "data": [row], "included": [], "identity_verified": False, "documented_credits": 1}
        if isinstance(cfg, PagedCompany): return await list_signals(data, cfg)
        raise ValueError("Use a native PredictLeads read operation")
