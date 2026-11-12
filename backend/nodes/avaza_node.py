"""Avaza native account-bound project, task, company and time metadata reads."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import logging
import math
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Dict, Literal, Optional, TypedDict, Union
from urllib.parse import quote, quote_plus
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode, runtime_config_view
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-avaza"
FAMILIES = ("avaza_access_token",)
BASE = "https://api.avaza.com"
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10000
SAFE_INTEGER = 9007199254740991
MAX_PARENT_ID = 2147483647


def _token(value):
    if not isinstance(value, str) or not 8<=len(value)<=4096 or any(ord(c)<=32 or ord(c)>=127 for c in value): raise ValueError("Supply an existing opaque Avaza access token without a header prefix")
    return value


def _text(value, *, maximum=4096):
    if not isinstance(value, str) or not value.strip() or len(value)>maximum or any(ord(c)<32 for c in value): raise ValueError("Supply nonempty metadata text within the local bound")
    return value


def _whole(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,16}", value): value=int(value)
    if type(value) is not int: raise ValueError("Supply a whole numeric ID or count")
    return value


def _id(value, *, maximum=SAFE_INTEGER):
    if type(value) is not int or not 1<=value<=maximum: raise ValueError("Unverified positive resource ID")
    return value


def _input_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value): raise ValueError("Supply an ISO8601 date-time with explicit timezone")
    try: datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: raise ValueError("Avaza date-time is invalid") from None
    return value


def _response_date(value):
    if value is None: return value
    if not isinstance(value, str) or len(value)>64 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,12})?(?:Z|[+-]\d{2}:\d{2})?", value): raise ValueError("Unverified ISO8601 response date-time")
    datetime.fromisoformat(value.replace("Z", "+00:00")); return value


class AvazaAccessTokenCredential(BaseModel):
    credential_type: Literal["avaza_access_token"] = Field("avaza_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Existing PAT or OAuth2 Access Token", json_schema_extra={"ui:widget": "password"})
    token_source: Literal["personal_access_token", "oauth2_access_token"] = Field("personal_access_token", title="Supplied Token Source", description="Caller-declared source, not decoded identity. OAuth access tokens expire; obtain a new existing token when required. No exchange or refresh is performed.")
    model_config = ConfigDict(title="Avaza Access Token", extra="ignore", json_schema_extra={
        "x-credential-url": "https://www.avaza.com/avaza-api-authentication-with-personal-access-tokens/",
        "x-credential-instructions": "Supply an existing Personal Access Token or issued OAuth2 access token. Both use Authorization: Bearer on fixed api.avaza.com. Required read scopes depend on the operations: read_account, read_contacts, read_projects and read_timesheets. PATs run under their creating user's roles and selected scopes. Protected /api/Account returns the actual AccountID; it does not identify the user or prove every permission/plan. No token creation/exchange/refresh, password, environment fallback or JWT identity decoding.",
    })
    _native_token = field_validator("access_token")(_token)


# Avaza's own MCP server: agents get its tools through a person's Avaza sign-in.
AvazaMcpCredential = mcp_credential("avaza", "https://mcp.avaza.com/mcp", app="Avaza")
AvazaCredential = Union[AvazaAccessTokenCredential, AvazaMcpCredential]


def _op(name, label, category):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


def _resource(field, resource, *, parent=None):
    options={"field_name": field, "searchable": True, "allow_custom": True}
    if parent: options["depends_on"] = parent
    return {"x-dynamic-options": options, "x-resource-type": resource, "x-resource-id-path": field}


class AvazaOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AvazaCheckConfig(AvazaOperation):
    operation: Literal["test_connection"] = _op("test_connection", "Check Account Read Access", "Connection")


class AvazaAccountScope(AvazaOperation):
    account_id: int = Field(..., ge=1, le=MAX_PARENT_ID, title="Account", description="Must match the actual protected /api/Account AccountID. No account ID is inferred from a token or resource lacking that field.", json_schema_extra=_resource("account_id", "avaza_account"))
    _account_id = field_validator("account_id", mode="before")(_whole)


class AvazaAccountConfig(AvazaAccountScope):
    operation: Literal["get_account"] = _op("get_account", "Read Bound Account Metadata", "Account")
    include_names: bool = Field(False, description="Explicitly return the account's CompanyName. Email/subdomain/currency/SC/feature flags and unknown fields remain omitted.")


class AvazaPage(AvazaAccountScope):
    page_size: int = Field(20, ge=1, le=1000, title="Page Size", description="One page. Companies/Projects/Timesheets publish maximum 1000; Task GET publishes default 20 but no maximum, so 1000 is only this client's local bound there.")
    page_token: Optional[str] = Field(None, max_length=8192, title="Next Page Token", description="Native current-account/credential/actor/query continuation. Local 15-minute validity, no traversal or snapshot claim.")
    include_names: bool = Field(False, description="Explicit resource company/title names. Notes/descriptions/contact/finance/rate/capability/unknown fields remain omitted.")
    _count = field_validator("page_size", mode="before")(_whole)


class AvazaCompaniesConfig(AvazaPage):
    operation: Literal["list_companies"] = _op("list_companies", "List Company Metadata", "Companies")
    search: Optional[str] = Field(None, max_length=512, description="Documented company-name search sent only to the minimal Company/Lookup endpoint.")
    @field_validator("search")
    @classmethod
    def query(cls, value): return _text(value, maximum=512) if value is not None else None


class AvazaCompanyScope(AvazaAccountScope):
    company_id: int = Field(..., ge=1, le=MAX_PARENT_ID, title="Company", json_schema_extra=_resource("company_id", "avaza_company", parent="account_id"))
    _company_id = field_validator("company_id", mode="before")(_whole)


class AvazaCompanyConfig(AvazaCompanyScope):
    operation: Literal["get_company"] = _op("get_company", "Read Bound Company Metadata", "Companies")
    include_names: bool = Field(False, description="Explicit CompanyName output. Contacts/address/phone/notes/tax/currency/custom fields/URLs remain omitted.")


class AvazaProjectsConfig(AvazaPage):
    operation: Literal["list_projects"] = _op("list_projects", "List Company Project Metadata", "Projects")
    company_id: int = Field(..., ge=1, le=MAX_PARENT_ID, title="Company", json_schema_extra=_resource("company_id", "avaza_company", parent="account_id"))
    include_archived: bool = Field(False, description="Explicit documented includeArchived filter; no project mutation.")
    _company_id = field_validator("company_id", mode="before")(_whole)


class AvazaProjectScope(AvazaCompanyScope):
    project_id: int = Field(..., ge=1, le=MAX_PARENT_ID, title="Project", description="Actual returned ProjectID and CompanyIDFK must match this selection.", json_schema_extra=_resource("project_id", "avaza_project", parent="company_id"))
    _project_id = field_validator("project_id", mode="before")(_whole)


class AvazaProjectConfig(AvazaProjectScope):
    operation: Literal["get_project"] = _op("get_project", "Read Bound Project Metadata", "Projects")
    include_names: bool = Field(False, description="Explicit title/company name/project code. Notes/rates/budgets/permissions/member contacts/unknown fields remain omitted.")


class AvazaTeamConfig(AvazaProjectScope):
    operation: Literal["list_project_team"] = _op("list_project_team", "Read Project Team Identifiers", "Projects")
    include_names: bool = Field(False, description="Explicit returned member first/last/full names. Email, every rate/budget/permission/approval/capability flag remain omitted.")


class AvazaTasksConfig(AvazaPage):
    operation: Literal["list_tasks"] = _op("list_tasks", "List Bound Project Tasks", "Tasks")
    company_id: int = Field(..., ge=1, le=MAX_PARENT_ID, title="Company", json_schema_extra=_resource("company_id", "avaza_company", parent="account_id"))
    project_id: int = Field(..., ge=1, le=MAX_PARENT_ID, title="Project", json_schema_extra=_resource("project_id", "avaza_project", parent="company_id"))
    is_complete: Optional[bool] = Field(None, description="Omitted unless explicitly set; documented isComplete filter. No invented status codes.")
    _ids = field_validator("company_id", "project_id", mode="before")(_whole)


class AvazaTaskConfig(AvazaProjectScope):
    operation: Literal["get_task"] = _op("get_task", "Read Bound Task Metadata", "Tasks")
    task_id: int = Field(..., ge=1, le=MAX_PARENT_ID, title="Task", json_schema_extra=_resource("task_id", "avaza_task", parent="project_id"))
    include_names: bool = Field(False, description="Explicit title/project/section names. Descriptions/assignee names/contact/attachments/custom fields/time totals remain omitted.")
    _task_id = field_validator("task_id", mode="before")(_whole)


class AvazaTimesheetsConfig(AvazaPage):
    operation: Literal["list_time_entries"] = _op("list_time_entries", "List Bound Time Entry Metadata", "Time")
    company_id: int = Field(..., ge=1, le=MAX_PARENT_ID, title="Company", json_schema_extra=_resource("company_id", "avaza_company", parent="account_id"))
    project_id: int = Field(..., ge=1, le=MAX_PARENT_ID, title="Project", json_schema_extra=_resource("project_id", "avaza_project", parent="company_id"))
    _ids = field_validator("company_id", "project_id", mode="before")(_whole)
    entry_date_from: str = Field(..., title="Entry Date From", description="Documented EntryDateFrom ISO8601 date-time. Positive local interval of at most 366 days; one page only.")
    entry_date_to: str = Field(..., title="Entry Date To", description="Documented EntryDateTo ISO8601 date-time; exact supplied values sent without timezone conversion.")
    _dates = field_validator("entry_date_from", "entry_date_to")(_input_date)
    @model_validator(mode="after")
    def interval(self):
        seconds=(datetime.fromisoformat(self.entry_date_to.replace("Z", "+00:00"))-datetime.fromisoformat(self.entry_date_from.replace("Z", "+00:00"))).total_seconds()
        if not 0<seconds<=366*86400: raise ValueError("Time-entry interval must be positive and at most 366 days locally")
        return self


class AvazaTimesheetConfig(AvazaProjectScope):
    operation: Literal["get_time_entry"] = _op("get_time_entry", "Read Bound Time Entry Metadata", "Time")
    time_entry_id: int = Field(..., ge=1, le=SAFE_INTEGER, title="Time Entry", description="Exact TimesheetEntryID. Manual existing ID only; public time-entry lookup is not invented.")
    include_names: bool = Field(False, description="Explicit project/customer/category/task titles only. User names/email/notes/invoice/rate/cost/approval-person/timer timestamps/unknown fields remain omitted.")
    _entry_id = field_validator("time_entry_id", mode="before")(_whole)


AvazaConfig = Annotated[Union[AvazaCheckConfig, AvazaAccountConfig, AvazaCompaniesConfig, AvazaCompanyConfig, AvazaProjectsConfig, AvazaProjectConfig, AvazaTeamConfig, AvazaTasksConfig, AvazaTaskConfig, AvazaTimesheetsConfig, AvazaTimesheetConfig], Field(discriminator="operation")]


class AvazaNodeConfig(NodeConfig[AvazaConfig, AvazaCredential]):
    pass


class AvazaResourceMetadata(TypedDict, total=False):
    CompanyID: int
    ProjectID: int
    CompanyIDFK: int
    TaskID: int
    ProjectIDFK: int
    TimesheetEntryID: int
    UserIDFK: int
    TaskIDFK: Optional[int]
    CompanyName: str
    Title: str
    ProjectStatusCode: str
    TaskStatusCode: str
    Duration: float
    EntryDate: Optional[str]
    DateCreated: Optional[str]
    DateUpdated: Optional[str]


class AvazaAPIError(ValueError):
    def __init__(self, message, *, authority_rejected=False, http_status=None):
        super().__init__(message)
        self.authority_rejected=authority_rejected
        self.http_status=http_status

def _shape(data):
    if not isinstance(data, dict) or data.get("credential_type", FAMILIES[0]) not in FAMILIES: raise ValueError("Avaza credential family is unsupported")
    try: shaped = AvazaAccessTokenCredential.model_validate({**data, "credential_type": FAMILIES[0]}).model_dump()
    except ValueError: raise ValueError("Avaza native credential is invalid") from None
    return shaped

def _binding(data):
    return (data["credential_type"], data["access_token"], data["token_source"])

def _bound_matches(bound, current):
    return _binding(bound) == _binding(current)

def _original_family(data):
    if not isinstance(data, dict):
        raise ValueError("Avaza configuration is invalid")
    creds = data.get("credentials")
    saved = data.get("credential_id") or data.get("credentialIds")
    if saved and not isinstance(creds, dict) or isinstance(creds, dict) and (creds.get("credential_type") is not None or saved) and creds.get("credential_type") not in FAMILIES:
        raise ValueError("Avaza saved credential family is missing or unsupported")


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
    # Match staging's credential resolution policy, including revocation and
    # positively authorized workflow-owner fallback. PATs are not refreshed.
    from utils.credentials import resolve_credential_with_owner_fallback
    if not user_id:
        raise ValueError("Avaza saved credential requires an authorized caller")
    if pool is None:
        from utils.database_pool import get_native_pool
        pool = get_native_pool()
    if organization_id is None:
        from wss.handlers.workflow_handler import get_user_org_context
        async with pool.acquire() as conn:
            organization_id = await get_user_org_context(conn, user_id)
    result = await resolve_credential_with_owner_fallback(
        credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id
    )
    if not isinstance(result, dict) or result.get("credential_type") not in FAMILIES:
        raise ValueError("Avaza current credential is unavailable or access denied")
    return {**_shape(result), "_avaza_authority": _LookupAuthority(pool, user_id, credential_id, organization_id, workflow_id)}


def _context(data, context):
    result = {k: v for k, v in context.items() if not k.startswith("_")}
    result["_user_id"] = context.get("_user_id")
    bound = data.get("_avaza_authority") if isinstance(data, dict) else None
    if type(bound) is _LookupAuthority:
        if bound.user_id != context.get("_user_id"):
            raise ValueError("Avaza picker actor does not match saved authority")
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
        return re.sub(r"(?i)([?&](?:access_token|api_key|token|signature|auth|key)=)[^&#\s]+", r"[redacted]", value)
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


# Narrow reuse of utils.meta_subscriptions._TransportPrivacy: context-local
# masking leaves concurrent unrelated requests untouched and resets on failure.
_PRIVATE_REQUEST = ContextVar("avaza_private_request", default=False)


class _TransportPrivacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE_REQUEST.get():
            record.msg, record.args = "Avaza private transport activity", ()
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
    except ValueError: raise AvazaAPIError("Avaza current credential authority is unavailable or revoked", authority_rejected=True) from None
    if _binding(current) != _binding(data): raise AvazaAPIError("Avaza current access token changed; result is not accepted", authority_rejected=True)
    return current


def _scope(data, context, query):
    return hashlib.sha256(_json([_binding(data), context.get("_credential_id"), context.get("_user_id"), context.get("_organization_id"), context.get("_workflow_id"), query])).hexdigest()


def _encode_cursor(data, context, query, page, issued):
    payload = base64.urlsafe_b64encode(_json({"page": page, "issued": issued, "scope": _scope(data, context, query)})).decode().rstrip("=")
    return payload+"."+hmac.new(data["access_token"].encode(), payload.encode(), hashlib.sha256).hexdigest()


def _decode_cursor(value, data, context, query):
    try:
        if not isinstance(value, str) or len(value)>8192 or not re.fullmatch(r"[A-Za-z0-9_-]+\.[0-9a-f]{64}", value): raise ValueError()
        payload, signature = value.split(".")
        if not hmac.compare_digest(signature, hmac.new(data["access_token"].encode(), payload.encode(), hashlib.sha256).hexdigest()): raise ValueError()
        decoded = _parse_json(base64.urlsafe_b64decode(payload+"="*((-len(payload))%4)))
        if not isinstance(decoded, dict) or set(decoded)!={"page", "issued", "scope"} or decoded["scope"]!=_scope(data, context, query): raise ValueError()
        if type(decoded["page"]) is not int or not 2<=decoded["page"]<=MAX_PARENT_ID or type(decoded["issued"]) is not int or not 0<=int(time.time())-decoded["issued"]<900: raise ValueError()
        return decoded["page"], decoded["issued"]
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("Avaza continuation expired or belongs to a different current credential/actor/account/parent/query; no automatic restart") from None


async def _request(data, context, route, *, params=None):
    if route not in ("/api/Account", "/api/Company/Lookup", "/api/Project", "/api/Task", "/api/Timesheet") and not re.fullmatch(r"/api/(?:Company|Project|Task|Timesheet)/[1-9][0-9]{0,15}", route):
        raise ValueError("Unsupported native Avaza GET route")
    current = await _stable(data, context)
    _protect_transport_logs(); private_token = _PRIVATE_REQUEST.set(True)
    try:
        try:
            async with guarded_async_client(timeout=20.0, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", BASE+route, params=params, headers={"Authorization": "Bearer "+current["access_token"], "Accept": "application/json"}) as response:
                    code = response.status_code
                    if code==403: raise AvazaAPIError("Avaza refused this protected read; key, role, scope and plan cause remain unverified", http_status=403)
                    if code==429: raise AvazaAPIError("Avaza rate limit refused this read (HTTP429); no retry", http_status=429)
                    if code!=200: raise AvazaAPIError("Avaza returned HTTP"+str(code)+"; protected read is unverified", http_status=code)
                    if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() not in ("application/json", "text/json"): raise AvazaAPIError("Avaza response is not documented JSON")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        chunks.extend(chunk)
                        if len(chunks)>MAX_BYTES: raise AvazaAPIError("Avaza response exceeds the local 8 MiB bound; no truncated success")
                    try: raw = _redact(_parse_json(chunks), current["access_token"])
                    except (ValueError, TypeError, UnicodeError, RecursionError): raise AvazaAPIError("Avaza JSON metadata is unverified") from None
        finally:
            # Recheck after success, refusal or transport uncertainty, without replay.
            await _stable(data, context)
        if not isinstance(raw, dict) or "error" in raw or "errors" in raw or raw.get("status") in ("error", "rejected", "pending_approval", "not_executed", "forbidden"):
            raise AvazaAPIError("Avaza did not return a documented successful read envelope")
        return raw
    except AvazaAPIError: raise
    except Exception: raise AvazaAPIError("Avaza transport did not establish a read result; no retry") from None
    finally: _PRIVATE_REQUEST.reset(private_token)


def _metadata(raw, *, ids=(), dates=(), texts=(), flags=(), include_names=False, names=()):
    if not isinstance(raw, dict): raise ValueError("Unverified metadata object")
    result={}
    for key in ids:
        if key in raw: result[key]=_id(raw[key]) if raw[key] is not None else None
    for key in dates:
        if key in raw: result[key]=_response_date(raw[key])
    for key in texts+ (names if include_names else ()):
        if key in raw:
            value=raw[key]
            if value is not None and (not isinstance(value, str) or len(value)>4096 or any(ord(c)<32 for c in value)): raise ValueError("Unverified metadata text")
            result[key]=value
    for key in flags:
        if key in raw:
            if type(raw[key]) is not bool: raise ValueError("Unverified metadata boolean")
            result[key]=raw[key]
    return result


def _account(raw, *, expected=None, include_names=False):
    try:
        item={"AccountID": _id(raw.get("AccountID"), maximum=MAX_PARENT_ID)}
        if expected is not None and item["AccountID"]!=expected: raise ValueError()
        item.update(_metadata(raw, include_names=include_names, names=("CompanyName",)))
        return item
    except (ValueError, TypeError, AttributeError): raise AvazaAPIError("Avaza protected AccountID is missing or differs from the selected account") from None


async def _account_witness(data, context, expected=None, *, include_names=False):
    return _account(await _request(data, context, "/api/Account"), expected=expected, include_names=include_names)


async def _scoped_request(data, context, account_id, route, *, params=None):
    await _account_witness(data, context, account_id)
    raw=await _request(data, context, route, params=params)
    await _account_witness(data, context, account_id)
    return raw


def _company(raw, *, expected=None, include_names=False):
    try:
        item={"CompanyID": _id(raw.get("CompanyID"))}
        if expected is not None and item["CompanyID"]!=expected: raise ValueError()
        item.update(_metadata(raw, dates=("DateCreated", "DateUpdated"), include_names=include_names, names=("CompanyName",)))
        return item
    except (ValueError, TypeError, AttributeError): raise AvazaAPIError("Avaza returned another company or unverified company metadata") from None


def _project(raw, *, company_id, expected=None, include_names=False):
    try:
        item={"ProjectID": _id(raw.get("ProjectID"), maximum=MAX_PARENT_ID), "CompanyIDFK": _id(raw.get("CompanyIDFK"), maximum=MAX_PARENT_ID)}
        if item["CompanyIDFK"]!=company_id or expected is not None and item["ProjectID"]!=expected: raise ValueError()
        item.update(_metadata(raw, dates=("StartDate", "EndDate", "DateCreated", "DateUpdated"), texts=("ProjectStatusCode", "ProjectStatusName"), flags=("isArchived",), include_names=include_names, names=("Title", "ProjectCode", "CompanyName")))
        return item
    except (ValueError, TypeError, AttributeError): raise AvazaAPIError("Avaza returned another project/company or unverified project metadata") from None


async def _project_witness(data, context, cfg, *, include_names=False):
    raw=await _scoped_request(data, context, cfg.account_id, "/api/Project/"+str(cfg.project_id))
    return raw, _project(raw, company_id=cfg.company_id, expected=cfg.project_id, include_names=include_names)


def _task(raw, *, project_id, expected=None, include_names=False):
    try:
        item={"TaskID": _id(raw.get("TaskID"), maximum=MAX_PARENT_ID), "ProjectIDFK": _id(raw.get("ProjectIDFK"), maximum=MAX_PARENT_ID)}
        if item["ProjectIDFK"]!=project_id or expected is not None and item["TaskID"]!=expected: raise ValueError()
        item.update(_metadata(raw, ids=("SectionIDFK", "ParentTaskIDFK"), dates=("DateStart", "DateDue", "DateCompleted", "DateCreated", "DateUpdated"), texts=("TaskStatusCode", "TaskStatusName", "TaskPriorityCode", "TaskPriorityName"), flags=("isCompleteStatus",), include_names=include_names, names=("Title", "ProjectTitle", "ProjectCode", "SectionTitle")))
        return item
    except (ValueError, TypeError, AttributeError): raise AvazaAPIError("Avaza returned another task/project or unverified task metadata") from None


def _time_entry(raw, *, project_id, company_id, expected=None, include_names=False):
    try:
        item={"TimesheetEntryID": _id(raw.get("TimesheetEntryID")), "ProjectIDFK": _id(raw.get("ProjectIDFK"), maximum=MAX_PARENT_ID)}
        if item["ProjectIDFK"]!=project_id or expected is not None and item["TimesheetEntryID"]!=expected: raise ValueError()
        if "CustomerIDFK" in raw:
            if _id(raw["CustomerIDFK"], maximum=MAX_PARENT_ID)!=company_id: raise ValueError()
            item["CustomerIDFK"]=company_id
        item.update(_metadata(raw, ids=("UserIDFK", "TaskIDFK"), dates=("EntryDate", "DateCreated", "DateUpdated"), texts=("TimesheetEntryApprovalStatusCode",), flags=("HasTimer",), include_names=include_names, names=("ProjectTitle", "CustomerName", "CategoryName", "TaskTitle")))
        if "Duration" in raw:
            value=raw["Duration"]
            if type(value) not in (int, float) or not math.isfinite(value): raise ValueError()
            item["Duration"]=value
        return item
    except (ValueError, TypeError, AttributeError): raise AvazaAPIError("Avaza returned another time entry/project/company or unverified time metadata") from None


def _team(raw, cfg):
    values=raw.get("Members")
    if not isinstance(values, list) or len(values)>MAX_ROWS: raise AvazaAPIError("Avaza project member collection is missing or exceeds the local bound")
    rows=[]; seen=set()
    try:
        for row in values:
            item={"UserIDFK": _id(row.get("UserIDFK"), maximum=MAX_PARENT_ID), "ProjectIDFK": _id(row.get("ProjectIDFK"), maximum=MAX_PARENT_ID)}
            if item["UserIDFK"] in seen or item["ProjectIDFK"]!=cfg.project_id: raise ValueError()
            seen.add(item["UserIDFK"])
            item.update(_metadata(row, include_names=cfg.include_names, names=("Firstname", "Lastname", "Fullname")))
            rows.append(item)
    except (ValueError, TypeError, AttributeError): raise AvazaAPIError("Avaza project team member/parent metadata is unverified") from None
    return rows


def _query(cfg, *, picker_search=""):
    params={"pageSize": cfg.page_size}; route=""; name=""
    if cfg.operation=="list_companies":
        route="/api/Company/Lookup"; name="Companies"
        if cfg.search is not None: params["search"]=cfg.search
    elif cfg.operation=="list_projects":
        route="/api/Project"; name="Projects"
        params.update({"CompanyID": cfg.company_id, "includeArchived": cfg.include_archived, "IncludeCustomFields": False, "IncludeBudget": False})
    elif cfg.operation=="list_tasks":
        route="/api/Task"; name="Tasks"; params.update({"ProjectID": cfg.project_id, "IncludeCustomFields": False})
        if cfg.is_complete is not None: params["isComplete"]=cfg.is_complete
    elif cfg.operation=="list_time_entries":
        route="/api/Timesheet"; name="Timesheets"; params.update({"ProjectID": cfg.project_id, "EntryDateFrom": cfg.entry_date_from, "EntryDateTo": cfg.entry_date_to, "includeInvoiceDetails": False})
    else: raise ValueError("Unsupported Avaza native collection")
    return {"route": route, "collection": name, "account_id": cfg.account_id, "company_id": getattr(cfg, "company_id", None), "project_id": getattr(cfg, "project_id", None), "params": params, "include_names": cfg.include_names, "picker_search": picker_search}


async def _page(data, context, cfg, *, picker_search=""):
    query=_query(cfg, picker_search=picker_search)
    number, issued=_decode_cursor(cfg.page_token, data, context, query) if cfg.page_token else (1, int(time.time()))
    if cfg.operation=="list_projects":
        _company(await _scoped_request(data, context, cfg.account_id, "/api/Company/"+str(cfg.company_id)), expected=cfg.company_id)
    elif cfg.operation in ("list_tasks", "list_time_entries"):
        await _project_witness(data, context, cfg)
    params={**query["params"], "pageNumber": number}
    wire={k: str(v).lower() if type(v) is bool else str(v) for k,v in params.items()}
    raw=await _scoped_request(data, context, cfg.account_id, query["route"], params=wire)
    values=raw.get(query["collection"])
    if not isinstance(values, list) or len(values)>cfg.page_size: raise AvazaAPIError("Avaza documented collection is missing or exceeds the requested page size")
    if type(raw.get("PageNumber")) is not int or raw["PageNumber"]!=number or type(raw.get("PageSize")) is not int or raw["PageSize"]!=cfg.page_size: raise AvazaAPIError("Avaza page number/size differs from the request")
    rows=[]; ids=set()
    for row in values:
        if cfg.operation=="list_companies": item=_company(row, include_names=cfg.include_names); identifier=item["CompanyID"]
        elif cfg.operation=="list_projects": item=_project(row, company_id=cfg.company_id, include_names=cfg.include_names); identifier=item["ProjectID"]
        elif cfg.operation=="list_tasks": item=_task(row, project_id=cfg.project_id, include_names=cfg.include_names); identifier=item["TaskID"]
        else: item=_time_entry(row, project_id=cfg.project_id, company_id=cfg.company_id, include_names=cfg.include_names); identifier=item["TimesheetEntryID"]
        if cfg.operation=="list_projects" and not cfg.include_archived and item.get("isArchived") is True: raise AvazaAPIError("Avaza returned an archived project outside the selected filter")
        if cfg.operation=="list_tasks" and cfg.is_complete is not None and item.get("isCompleteStatus") is not cfg.is_complete: raise AvazaAPIError("Avaza returned an unverified task completion filter")
        if identifier in ids: raise AvazaAPIError("Avaza page repeats a resource ID")
        ids.add(identifier); rows.append(item)
    total=raw.get("TotalCount"); end=(number-1)*cfg.page_size+len(rows)
    if type(total) is not int or not end<=total<=MAX_PARENT_ID: raise AvazaAPIError("Avaza total count conflicts with the observed page")
    has_next=end<total
    if has_next and len(rows)!=cfg.page_size: raise AvazaAPIError("Avaza page is short before the reported total; continuation completeness is unverified")
    next_token=_encode_cursor(data, context, query, number+1, issued) if has_next else None
    return rows, {"page_number": number, "page_size": cfg.page_size, "returned_count": len(rows), "provider_total": total, "has_next": has_next, "next_page_token": next_token, "provider_reported_complete": not has_next, "one_page_only": True, "snapshot_verified": False, "completion_scope": "current reported numeric page, not a stable complete-account snapshot"}


class AvazaNode(WorkflowNode):
    integration_type = "automation-avaza"
    credential_provider_labels = {"avaza": "Avaza Account"}
    workflow_credential_refresh=True
    connection_evidence=ConnectionEvidence(operation="test_connection", noun="Avaza account", proves="account", label_keys=("AccountID",))
    edit_examples=["List project metadata under a selected account and company", "Read selected project task status without descriptions or assignees", "List time entry metadata over one bounded date interval"]
    @classmethod
    def get_config_model(cls): return AvazaNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        _original_family(config_data); shaped=dict(config_data)
        if config_data.get("credentials") is not None: shaped["credentials"]=_shape(config_data["credentials"])
        try: AvazaNodeConfig.model_validate(runtime_config_view(shaped, AvazaNodeConfig))
        except ValueError: raise ValueError("Avaza native configuration, parent/date scope or credential is invalid") from None
        return super().parse_config(shaped)
    @classmethod
    def validate_config(cls, config_data):
        try:
            _original_family(config_data); shaped=dict(config_data)
            if config_data.get("credentials") is not None: shaped["credentials"]=_shape(config_data["credentials"])
            AvazaNodeConfig.model_validate(runtime_config_view(shaped, AvazaNodeConfig))
        except (ValueError, TypeError): return ValidationResult(valid=False, errors=["Avaza native configuration or credential family is invalid"], satisfied_set=None)
        return super().validate_config(shaped)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # The dropdown dispatcher has already resolved current credentials with
        # its workflow/organization context. Supplied PATs have no refresh flow.
        return _shape(credential_data)
    @classmethod
    async def validate_credential_access(cls, data):
        # Staging's connect path performs the provider probe via
        # connection_evidence; this hook validates the credential shape.
        try:
            _shape(data)
        except ValueError:
            return {"valid": False, "error": "Supply an existing Avaza access token"}
        return {"valid": True}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, AvazaNodeConfig) or self.config.credentials is None: raise ValueError("Avaza requires an existing native access token")
        node_data=self.node_data or {}; raw=node_data.get("credentials")
        data=_shape(raw if isinstance(raw, dict) else self.config.credentials.model_dump())
        context={"_approval_pool": node_data.get("_approval_pool"), "_credential_id": node_data.get("credential_id"), "_user_id": self.user_id, "_organization_id": self.organization_id, "_workflow_id": self.workflow_id}
        current=await _current_data(data, **_authority(context))
        if node_data.get("credential_id") and not _bound_matches(data, current): raise AvazaAPIError("Avaza saved-row binding changed before transport", authority_rejected=True)
        result=await self._operation(self.config.config, current, context)
        await _stable(current, context)
        return {"status": "success", "operation": self.config.config.operation, "data": result}
    @staticmethod
    async def _operation(cfg, data, context):
        if cfg.operation=="test_connection":
            account=await _account_witness(data, context)
            return {**account, "results": [account], "protected_read_completed": True, "account_identity_verified": True, "user_identity_verified": False, "all_permissions_verified": False, "entitlement_verified": False}
        if cfg.operation=="get_account":
            return {"account": await _account_witness(data, context, cfg.account_id, include_names=cfg.include_names), "account_identity_verified": True, "names_included": cfg.include_names, "user_identity_verified": False, "all_permissions_verified": False}
        common={"account_id": cfg.account_id, "account_witness_verified": True, "user_identity_verified": False, "names_included": cfg.include_names, "contact_notes_finance_capabilities_omitted": True}
        if cfg.operation in ("list_companies", "list_projects", "list_tasks", "list_time_entries"):
            rows, page=await _page(data, context, cfg)
            key={"list_companies": "companies", "list_projects": "projects", "list_tasks": "tasks", "list_time_entries": "time_entries"}[cfg.operation]
            return {**common, key: rows, "pagination": page, "next_page_token": page["next_page_token"]}
        if cfg.operation=="get_company":
            row=_company(await _scoped_request(data, context, cfg.account_id, "/api/Company/"+str(cfg.company_id)), expected=cfg.company_id, include_names=cfg.include_names)
            return {**common, "company": row, "returned_company_id_verified": True}
        if cfg.operation in ("get_project", "list_project_team"):
            raw, project=await _project_witness(data, context, cfg, include_names=cfg.include_names)
            if cfg.operation=="get_project": return {**common, "project": project, "returned_project_company_verified": True}
            rows=_team(raw, cfg)
            return {**common, "members": rows, "returned_count": len(rows), "project_id": cfg.project_id, "company_id": cfg.company_id, "returned_project_company_member_parent_verified": True, "documented_unpaged_members_observed": True}
        if cfg.operation in ("get_task", "get_time_entry"):
            await _project_witness(data, context, cfg)
            if cfg.operation=="get_task":
                row=_task(await _scoped_request(data, context, cfg.account_id, "/api/Task/"+str(cfg.task_id)), project_id=cfg.project_id, expected=cfg.task_id, include_names=cfg.include_names)
                return {**common, "task": row, "returned_task_project_company_verified": True}
            row=_time_entry(await _scoped_request(data, context, cfg.account_id, "/api/Timesheet/"+str(cfg.time_entry_id)), project_id=cfg.project_id, company_id=cfg.company_id, expected=cfg.time_entry_id, include_names=cfg.include_names)
            return {**common, "time_entry": row, "returned_time_entry_project_company_verified": True}
        raise ValueError("Unsupported native Avaza operation")
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        if field_name not in ("account_id", "company_id", "project_id", "task_id"): return {"options": [], "next_page_token": None}
        context=_context(credential_data, context or {})
        args={}
        if field_name!="account_id": args["account_id"]=_id(_whole(context.get("account_id")), maximum=MAX_PARENT_ID)
        if field_name in ("project_id", "task_id"): args["company_id"]=_id(_whole(context.get("company_id")), maximum=MAX_PARENT_ID)
        if field_name=="task_id": args["project_id"]=_id(_whole(context.get("project_id")), maximum=MAX_PARENT_ID)
        if search not in (None, ""): _text(search, maximum=512)
        if field_name=="account_id" and page_token: raise ValueError("Avaza account read has no published pagination")
        data=await _current_data(credential_data, **_authority(context))
        if field_name=="account_id":
            row=await _account_witness(data, context); identifier=str(row["AccountID"])
            options=[{"value": identifier, "label": identifier}] if not search or search.casefold() in identifier.casefold() else []; next_token=None
        else:
            config_type={"company_id": AvazaCompaniesConfig, "project_id": AvazaProjectsConfig, "task_id": AvazaTasksConfig}[field_name]
            if field_name=="company_id" and search: args["search"]=search
            cfg=config_type(**args, page_size=100, page_token=page_token, include_names=False)
            rows, page=await _page(data, context, cfg, picker_search=search or "")
            key={"company_id": "CompanyID", "project_id": "ProjectID", "task_id": "TaskID"}[field_name]
            # Only company-name search has a documented wire filter. Other picker
            # searches match ID strings locally and retain the original continuation.
            if field_name!="company_id" and search: rows=[row for row in rows if search.casefold() in str(row[key]).casefold()]
            options=[{"value": str(row[key]), "label": str(row[key])} for row in rows]; next_token=page["next_page_token"]
        await _stable(data, context)
        return {"options": options, "next_page_token": next_token}
