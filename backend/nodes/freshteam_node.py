"""Native Freshteam tenant catalogs, recruiting and employee metadata.

Issued API keys use Bearer authentication on a code-owned tenant host. The
linked vendor SDK supplements the REST reference for job-bound applicants.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_serializer
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.credentials import resolve_credential_with_owner_fallback
from utils.ssrf import guarded_async_client, normalize_provider_subdomain

TYPE = "freshteam"
_CURRENT_ORG = object()
_AUTH_KEY = "_freshteam_authority"
_UNAVAILABLE = "Freshteam credential is unavailable or access changed"
_INVALID = "Freshteam returned an unexpected response; this outcome is unverified"
MAX_ID = 9007199254740991
ID = Annotated[StrictStr, Field(min_length=1, max_length=16, pattern=r"^[1-9][0-9]{0,15}$")]
FieldName = Annotated[StrictStr, Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$")]


def _tenant(value):
    if not isinstance(value, str) or value != value.strip() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Enter the exact Freshteam account name or HTTPS tenant origin")
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port is not None or not (parsed.hostname or "").endswith(".freshteam.com"):
            raise ValueError("Use the owned HTTPS Freshteam tenant origin without a path, port or query")
    elif any(c in value for c in "/?#:@"):
        raise ValueError("Use a single Freshteam account label")
    return normalize_provider_subdomain(value, "freshteam.com", field_name="Freshteam account", allow_nested_labels=False)


class FreshteamCredential(BaseModel):
    model_config = ConfigDict(title="Freshteam", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://support.freshteam.com/support/solutions/articles/19000107072-how-to-use-freshteam-developer-api-",
        "x-credential-instructions": "Supply the API key already issued in your Freshteam profile > API Settings and your owned account name. Requests use Authorization: Bearer on that account only. No OAuth app, password login or token minting is performed; read permissions and plan access remain operation-specific.",
    })
    credential_type: Literal["freshteam"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    account_name: StrictStr = Field(..., title="Freshteam Account", description="Your account label or exact https://account.freshteam.com origin. Other Freshworks products and arbitrary hosts are not accepted.")
    api_key: Annotated[StrictStr, Field(min_length=1, max_length=4096)] = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("account_name")
    @classmethod
    def account(cls, value):
        return _tenant(value)

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use the exact issued API key without whitespace")
        return value

    @model_serializer(mode="wrap")
    def connect_type(self, handler):
        # Visible-only manual forms omit the hidden discriminator.
        return {**handler(self), "credential_type": TYPE}


def _credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
        raise ValueError("A Freshteam API-key credential is required")
    try:
        return FreshteamCredential.model_validate(raw)
    except Exception:
        raise ValueError("Freshteam credential fields are invalid") from None


def _raw_guard(data):
    raw = data.get("credentials") if isinstance(data, dict) else None
    if isinstance(raw, dict) and "credential_type" in raw and raw["credential_type"] != TYPE:
        raise ValueError("A Freshteam API-key credential is required")


def op(name, title, category):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": title, "x-category": category, "x-is-trigger": False})


def picker(name, parent=None):
    value = {"field_name": name, "allow_custom": True, "searchable": False, "custom_placeholder": "Exact Freshteam ID or field name"}
    if parent:
        value["depends_on"] = parent
    return {"x-dynamic-options": value}


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", check_fields=False)
    @classmethod
    def bounded_id(cls, value, info):
        if info.field_name.endswith("_id") and value is not None and int(value) > MAX_ID:
            raise ValueError("Freshteam ID exceeds the native safe-integer bound")
        return value


class CheckConnection(Config):
    operation: Literal["check_connection"] = op("check_connection", "Check Tenant API Access", "Connection")


class ListDepartments(Config):
    operation: Literal["list_departments"] = op("list_departments", "List Departments", "Organization")


class ListBranches(Config):
    operation: Literal["list_branches"] = op("list_branches", "List Branch Metadata", "Organization")


class ListTeams(Config):
    operation: Literal["list_teams"] = op("list_teams", "List Teams", "Organization")


class ListSubDepartments(Config):
    operation: Literal["list_sub_departments"] = op("list_sub_departments", "List Sub-Departments", "Organization")


class ListBusinessUnits(Config):
    operation: Literal["list_business_units"] = op("list_business_units", "List Business Units", "Organization")


class ListLevels(Config):
    operation: Literal["list_levels"] = op("list_levels", "List Job Levels", "Organization")


class ListUserFunctions(Config):
    operation: Literal["list_user_functions"] = op("list_user_functions", "List User Functions", "Organization")


class Page(Config):
    page: Annotated[StrictInt, Field(ge=1, le=10000)] = Field(1, title="Page", description="One page per request. Freshteam documents 50 records per page; the node does not follow response URLs or scan automatically.")


class ListEmployees(Page):
    operation: Literal["list_employees"] = op("list_employees", "List Employee Metadata", "Employees")
    department_id: Optional[ID] = Field(None, json_schema_extra=picker("department_id"))
    branch_id: Optional[ID] = Field(None, json_schema_extra=picker("branch_id"))
    status: Optional[Literal["active", "inactive"]] = None


class GetEmployee(Config):
    operation: Literal["get_employee"] = op("get_employee", "Get Employee Metadata", "Employees")
    employee_id: ID = Field(..., json_schema_extra=picker("employee_id"))


class ListJobs(Page):
    operation: Literal["list_jobs"] = op("list_jobs", "List Job Posting Metadata", "Recruiting")
    title: Optional[Annotated[StrictStr, Field(min_length=1, max_length=200)]] = None
    status: Optional[Literal["draft", "published", "internal", "private", "on_hold", "closed"]] = None
    department_id: Optional[ID] = Field(None, json_schema_extra=picker("department_id"))
    branch_id: Optional[ID] = Field(None, json_schema_extra=picker("branch_id"))
    remote: Optional[StrictBool] = Field(None, description="Unset leaves the filter out. False explicitly selects non-remote jobs.")


class Job(Config):
    job_id: ID = Field(..., json_schema_extra=picker("job_id"))


class GetJob(Job):
    operation: Literal["get_job"] = op("get_job", "Get Job Posting Metadata", "Recruiting")


class ListJobFields(Config):
    operation: Literal["list_job_fields"] = op("list_job_fields", "List Job Form Field Metadata", "Recruiting")


class ListApplicantFields(Job):
    operation: Literal["list_applicant_fields"] = op("list_applicant_fields", "List Job Applicant Field Metadata", "Recruiting")


class ListApplicants(Job, Page):
    operation: Literal["list_applicants"] = op("list_applicants", "List Job Applicant Metadata", "Recruiting")
    status: Optional[Literal["open", "on_hold", "rejected", "archived", "moved", "dropped"]] = None


class Applicant(Job):
    applicant_id: ID = Field(..., json_schema_extra=picker("applicant_id", "job_id"))


class GetApplicant(Applicant):
    operation: Literal["get_applicant"] = op("get_applicant", "Get Job Applicant Metadata", "Recruiting")
    field_name: Optional[FieldName] = Field(None, description="Optionally read one qualified custom text metadata field for an explicit write readback.", json_schema_extra=picker("field_name", "job_id"))


class UpdateApplicantTextField(Applicant):
    operation: Literal["update_applicant_text_field"] = op("update_applicant_text_field", "Update Applicant Custom Text Metadata", "Recruiting")
    field_name: FieldName = Field(..., title="Custom Text Field", description="Existing non-default applicant text/paragraph field from the selected job. Use a non-sensitive internal CRM metadata field; no hiring-stage or employee changes.", json_schema_extra=picker("field_name", "job_id"))
    value: Annotated[StrictStr, Field(min_length=1, max_length=1000)] = Field(..., description="Replaces this text metadata. The node refuses applicants with other populated custom fields because sparse-map preservation is not documented.")


class ListCandidateSources(Config):
    operation: Literal["list_candidate_sources"] = op("list_candidate_sources", "List Candidate Sources", "Recruiting Reference")


class ListSourceCategories(Config):
    operation: Literal["list_source_categories"] = op("list_source_categories", "List Candidate Source Categories", "Recruiting Reference")


class CreateCandidateSource(Config):
    operation: Literal["create_candidate_source"] = op("create_candidate_source", "Create Candidate Source Metadata", "Recruiting Reference")
    label: Annotated[StrictStr, Field(min_length=2, max_length=128)] = Field(..., description="Creates an account-wide recruiting source. No documented API delete is exposed; root must qualify owned UI cleanup before a real lifecycle.")


class FreshteamNodeConfig(NodeConfig):
    model_config = ConfigDict(hide_input_in_errors=True)
    credentials: Optional[FreshteamCredential] = None
    config: Annotated[Union[CheckConnection, ListDepartments, ListBranches, ListTeams, ListSubDepartments, ListBusinessUnits, ListLevels, ListUserFunctions, ListEmployees, GetEmployee, ListJobs, GetJob, ListJobFields, ListApplicantFields, ListApplicants, GetApplicant, UpdateApplicantTextField, ListCandidateSources, ListSourceCategories, CreateCandidateSource], Field(discriminator="operation")]


@dataclass
class _Authority:
    credential: Any = field(repr=False)
    pool: Any = field(default=None, repr=False)
    credential_id: Optional[str] = None
    user_id: Optional[str] = None
    org_id: Optional[str] = None
    workflow_id: Optional[str] = None

    @classmethod
    async def create(cls, raw, *, pool=None, user_id=None, credential_id=None, organization_id=_CURRENT_ORG, workflow_id=None):
        original = _credential(raw)
        if credential_id and not user_id:
            raise ValueError(_UNAVAILABLE)
        if not credential_id:
            return cls(original)
        if pool is None:
            from utils.database_pool import get_native_pool
            pool = get_native_pool()
        if organization_id is _CURRENT_ORG:
            from wss.handlers.workflow_handler import get_user_org_context
            async with pool.acquire() as conn:
                organization_id = await get_user_org_context(conn, user_id)
        current = cls(original, pool, credential_id, user_id, organization_id, workflow_id)
        current.credential = await current._load()
        return current

    async def _load(self):
        # Use staging's runner/authorized-owner/lender resolution policy. The
        # issued API key does not expire; reload it around provider requests.
        try:
            raw = await resolve_credential_with_owner_fallback(
                self.credential_id, self.user_id, self.pool,
                org_id=self.org_id, workflow_id=self.workflow_id,
            )
            if raw is None:
                raise ValueError(_UNAVAILABLE)
            credential = _credential(raw)
        except Exception:
            raise ValueError(_UNAVAILABLE) from None
        return credential

    async def require_current(self):
        if self.credential_id:
            credential = await self._load()
            if credential != self.credential:
                raise ValueError(_UNAVAILABLE)


class FreshteamApiError(ValueError):
    def __init__(self, status):
        self.status_code = status
        super().__init__({401: "Freshteam rejected the API key", 403: "Freshteam denied this operation; key validity is unverified", 404: "Freshteam resource was not found", 422: "Freshteam rejected the metadata fields", 429: "Freshteam rate limit reached; retry later"}.get(status, "Freshteam request outcome is unverified"))


async def _request(authority, method, path, *, params=None, body=None, expected=200):
    await authority.require_current()
    headers = {"Accept": "application/json", "User-Agent": "NoClick-Freshteam/1.0", "Authorization": "Bearer " + authority.credential.api_key}
    origin = "https://" + authority.credential.account_name + ".freshteam.com"
    try:
        async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, origin + "/api/" + path, params=params, json=body, headers=headers) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > 1048576:
                        raise ValueError("Freshteam response exceeded the native bound")
                    raw.extend(chunk)
                await authority.require_current()
                if response.status_code != expected:
                    raise FreshteamApiError(response.status_code)
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError(_INVALID)
                def pairs(entries):
                    value = {}
                    for key, item in entries:
                        if key in value:
                            raise ValueError
                        value[key] = item
                    return value
                try:
                    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    if not isinstance(value, (dict, list)):
                        raise ValueError
                except (ValueError, UnicodeError, RecursionError):
                    raise ValueError(_INVALID) from None
                # Never return Location/Link or arbitrary provider headers/URLs.
                paging = {}
                for key in ("total-pages", "total-objects", "per-page"):
                    if key in response.headers:
                        header = response.headers[key]
                        if not re.fullmatch(r"[0-9]{1,10}", header):
                            raise ValueError(_INVALID)
                        paging[key] = int(header)
                return value, paging
    except httpx.RequestError:
        await authority.require_current()
        raise ValueError("Freshteam transport outcome is unverified") from None


def _number(value, minimum=1):
    if type(value) is not int or not minimum <= value <= MAX_ID:
        raise ValueError(_INVALID)
    return value


def _project(raw, names):
    if not isinstance(raw, dict):
        raise ValueError(_INVALID)
    result = {}
    for name in names:
        if name in raw:
            value = raw[name]
            if value is not None and (type(value) not in (str, bool, int) or (type(value) is str and len(value) > 4096)):
                raise ValueError(_INVALID)
            result[name] = value
    return result


_BASE = ("created_at", "updated_at", "deleted")
_FIELDS = {
    "department": ("name",), "sub_department": ("name",), "business_unit": ("name",),
    "team": ("name",), "level": ("name",), "user_function": ("value", "position"),
    "branch": ("name", "city", "state", "country_code", "time_zone", "currency", "language", "main_office"),
    "employee": ("first_name", "last_name", "designation", "employee_type", "status", "branch_id", "team_id", "department_id", "sub_department_id", "business_unit_id"),
    "job": ("title", "status", "type", "remote", "applicant_access_type"),
    "source": ("label", "default", "leads_count"),
    "field": ("name", "label", "field_type", "base_model", "default", "position", "applicant_form_id"),
    "applicant": ("status", "stage", "stage_id", "sub_stage_id", "job_id", "requisition_id", "applicant_source_id", "applicant_source_category_id"),
}


def _record(raw, kind, resource_id=None, parent_id=None):
    if not isinstance(raw, dict):
        raise ValueError(_INVALID)
    identity = _number(raw.get("id"))
    if resource_id is not None and identity != int(resource_id):
        raise ValueError("Freshteam returned a different resource ID")
    result = {"id": identity, **_project(raw, _BASE + _FIELDS[kind])}
    for key, value in result.items():
        if key.endswith("_id") and value is not None:
            _number(value)
        if key in {"deleted", "default", "main_office", "remote"} and type(value) is not bool:
            raise ValueError(_INVALID)
        if key in {"position", "leads_count"} and value is not None:
            _number(value, minimum=0)
        if key in {"created_at", "updated_at", "name", "label", "title", "first_name", "last_name", "designation", "employee_type", "status", "value", "field_type", "base_model", "stage", "type", "applicant_access_type", "city", "state", "country_code", "time_zone", "currency", "language"} and value is not None and not isinstance(value, str):
            raise ValueError(_INVALID)
    if kind == "employee":
        if any(not isinstance(result.get(key), str) or not result[key] for key in ("first_name", "last_name")):
            raise ValueError(_INVALID)
    elif kind == "applicant":
        if parent_id is None or _number(raw.get("job_id")) != int(parent_id):
            raise ValueError("Freshteam applicant is outside the selected job")
        candidate = raw.get("candidate")
        names = _project(candidate, ("first_name", "last_name"))
        if any(not isinstance(names.get(key), str) or not names[key] for key in ("first_name", "last_name")):
            raise ValueError(_INVALID)
        if "id" in candidate:
            names["id"] = _number(candidate["id"])
        result["candidate"] = names
    else:
        name = "value" if kind == "user_function" else "title" if kind == "job" else "label" if kind in {"source", "field"} else "name"
        if not isinstance(result.get(name), str) or not result[name]:
            raise ValueError(_INVALID)
    if kind == "job":
        for key in ("branch", "department"):
            if key in raw and raw[key] is not None:
                result[key] = _record(raw[key], key)
    return result


def _collection(response, kind, *, page=None, parent_id=None):
    raw, headers = response
    bound = 50 if page is not None else 200
    if not isinstance(raw, list) or len(raw) > bound:
        raise ValueError("Freshteam collection exceeds the native bound or is malformed")
    rows = [_record(row, kind, parent_id=parent_id) for row in raw]
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError(_INVALID)
    total_pages = headers.get("total-pages")
    if total_pages is not None and page is not None and total_pages < page and not (total_pages == 0 and page == 1 and not rows):
        raise ValueError(_INVALID)
    result = {"items": rows, "automatic_paging": False, "pagination_verified": total_pages is not None, "next_page": None}
    if page is not None:
        result["page"] = page
        if total_pages is not None and page < total_pages and page < 10000:
            result["next_page"] = page + 1
    else:
        # Catalog routes have no page parameter in the linked OpenAPI.
        result["complete_catalog_verified"] = total_pages in (0, 1)
    if total_pages is not None:
        result["total_pages"] = total_pages
    if "total-objects" in headers:
        result["total_objects"] = headers["total-objects"]
    return result


_LISTS = {
    "list_departments": ("departments", "department"), "list_branches": ("branches", "branch"),
    "list_teams": ("teams", "team"), "list_sub_departments": ("sub_departments", "sub_department"),
    "list_business_units": ("business_units", "business_unit"), "list_levels": ("levels", "level"),
    "list_user_functions": ("user_functions", "user_function"), "list_candidate_sources": ("candidate_sources", "source"),
    "list_source_categories": ("candidate_source_categories", "source"), "list_job_fields": ("job_posting_fields", "field"),
}


def _custom_text(row):
    return row.get("default") is False and row.get("deleted") is not True and row.get("base_model") == "applicant" and row.get("field_type") in {"text", "paragraph"} and isinstance(row.get("name"), str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", row["name"]) is not None


class FreshteamNode(WorkflowNode):
    integration_type = "automation-freshteam"
    connection_evidence = ConnectionEvidence(identity_operation="check_connection", identity_keys=("tenant_host",), noun="Freshteam tenant API access", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return FreshteamNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        _raw_guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        _raw_guard(config_data)
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        try:
            authority = await _Authority.create(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
        except Exception:
            raise ValueError(_UNAVAILABLE) from None
        return {**authority.credential.model_dump(), _AUTH_KEY: authority}

    @classmethod
    async def validate_credential_access(cls, raw, *, validation_context=None):
        try:
            if validation_context is not None:
                result = await validation_context.run_operation("check_connection", {})
                return (True, None) if result.get("status") == "success" else (None, "Freshteam access is unverified")
            authority = await _Authority.create(raw)
            _collection(await _request(authority, "GET", "departments"), "department")
            await authority.require_current()
            return True, None
        except FreshteamApiError as exc:
            return (False, str(exc)) if exc.status_code == 401 else (None, str(exc))
        except Exception:
            if validation_context is not None:
                await validation_context.revalidate()
            return None, "Freshteam access is unverified"

    async def execute(self, input_data):
        _raw_guard(self.node_data)
        if self.config.credentials is None:
            raise ValueError("Freshteam credentials are required")
        args = self.config.config
        action = args.operation
        authority = await _Authority.create(self.config.credentials.model_dump(), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data.get("credential_id"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        async def exact(kind, path, resource_id, parent=None):
            raw, _ = await _request(authority, "GET", path)
            return raw, _record(raw, kind, resource_id, parent)
        if action == "check_connection":
            _collection(await _request(authority, "GET", "departments"), "department")
            data = {"tenant_host": authority.credential.account_name + ".freshteam.com", "api_access_accepted": True, "authenticated_identity_available": False, "operation_permissions_verified": False}
        elif action in _LISTS:
            path, kind = _LISTS[action]
            data = _collection(await _request(authority, "GET", path), kind)
        elif action in {"list_employees", "list_jobs"}:
            params = {"page": args.page}
            for field_name, route, kind, query in (("department_id", "departments", "department", "department"), ("branch_id", "branches", "branch", "location")):
                chosen = getattr(args, field_name)
                if chosen is not None:
                    await exact(kind, route + "/" + chosen, chosen)
                    params[query] = chosen
            if args.status is not None:
                params["status"] = args.status
            if action == "list_jobs":
                if args.title is not None:
                    params["title"] = args.title
                if args.remote is not None:
                    params["remote"] = "true" if args.remote else "false"
            data = _collection(await _request(authority, "GET", "employees" if action == "list_employees" else "job_postings", params=params), "employee" if action == "list_employees" else "job", page=args.page)
            for row in data["items"]:
                for field_name, resource in (("department_id", "department"), ("branch_id", "branch")):
                    chosen = getattr(args, field_name)
                    if chosen is not None:
                        actual = row.get(field_name) if action == "list_employees" else (row.get(resource) or {}).get("id")
                        if actual != int(chosen):
                            raise ValueError("Freshteam record is outside the selected organization scope")
        elif action in {"get_employee", "get_job"}:
            kind, route = ("employee", "employees") if action == "get_employee" else ("job", "job_postings")
            resource_id = getattr(args, kind + "_id")
            _, data = await exact(kind, route + "/" + resource_id, resource_id)
        elif action in {"list_applicant_fields", "list_applicants", "get_applicant", "update_applicant_text_field"}:
            await exact("job", "job_postings/" + args.job_id, args.job_id)
            if action == "list_applicant_fields":
                data = _collection(await _request(authority, "GET", "job_postings/" + args.job_id + "/applicant_fields"), "field")
            elif action == "list_applicants":
                params = {"page": args.page}
                if args.status is not None:
                    params["status"] = args.status
                data = _collection(await _request(authority, "GET", "job_postings/" + args.job_id + "/applicants", params=params), "applicant", page=args.page, parent_id=args.job_id)
            else:
                path = "applicants/" + args.applicant_id
                raw, data = await exact("applicant", path, args.applicant_id, args.job_id)
                if action == "get_applicant" and args.field_name is not None:
                    fields = _collection(await _request(authority, "GET", "job_postings/" + args.job_id + "/applicant_fields"), "field")
                    chosen = [row for row in fields["items"] if row.get("name") == args.field_name and _custom_text(row)]
                    custom = raw.get("custom_fields")
                    if len(chosen) != 1 or not isinstance(custom, dict) or args.field_name not in custom:
                        raise ValueError("Freshteam custom text readback is unavailable")
                    value = custom[args.field_name]
                    if value is not None and (not isinstance(value, str) or len(value) > 1000):
                        raise ValueError(_INVALID)
                    data["text_metadata"] = {"field_name": args.field_name, "value": value}
                if action == "update_applicant_text_field":
                    fields = _collection(await _request(authority, "GET", "job_postings/" + args.job_id + "/applicant_fields"), "field")
                    candidates = [row for row in fields["items"] if row.get("name") == args.field_name and _custom_text(row)]
                    old = raw.get("custom_fields")
                    if len(candidates) != 1 or not isinstance(old, dict) or any(name != args.field_name and value is not None for name, value in old.items()):
                        raise ValueError("Only an existing applicant custom text field with no other populated custom fields may be updated")
                    body = {"custom_fields": {args.field_name: args.value}}
                    updated, _ = await _request(authority, "PUT", path, body=body)
                    data = _record(updated, "applicant", args.applicant_id, args.job_id)
                    if not isinstance(updated.get("custom_fields"), dict) or updated["custom_fields"].get(args.field_name) != args.value:
                        raise ValueError("Freshteam did not acknowledge the requested text field; reconcile before retrying")
                    data.update({"field_name": args.field_name, "write_acknowledged": True, "readback_verified": False, "readback_operation": "get_applicant"})
        elif action == "create_candidate_source":
            raw, _ = await _request(authority, "POST", "candidate_sources", body={"label": args.label}, expected=201)
            data = _record(raw, "source")
            if data.get("label") != args.label or data.get("default") is not False:
                raise ValueError("Freshteam did not acknowledge the new custom source; reconcile before retrying")
            data.update({"write_acknowledged": True, "readback_verified": False, "readback_operation": "list_candidate_sources", "cleanup_method": "owned Freshteam UI; API delete unavailable"})
        else:
            raise ValueError("Unsupported Freshteam operation")
        await authority.require_current()
        return {"status": "success", "operation": action, "data": data}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if not isinstance(credential_data, dict) or field_name not in {"department_id", "branch_id", "employee_id", "job_id", "applicant_id", "field_name"} or (context is not None and not isinstance(context, dict)):
            raise ValueError("Unsupported Freshteam picker context")
        if search:
            raise ValueError("Freshteam pickers do not guess a search filter; use an exact custom ID")
        if page_token is not None and (not isinstance(page_token, str) or not re.fullmatch(r"[1-9][0-9]{0,4}", page_token) or int(page_token) > 10000):
            raise ValueError("Invalid Freshteam picker page")
        mapping = {"department_id": "list_departments", "branch_id": "list_branches", "employee_id": "list_employees", "job_id": "list_jobs", "applicant_id": "list_applicants", "field_name": "list_applicant_fields"}
        args = {"operation": mapping[field_name]}
        if field_name in {"employee_id", "job_id", "applicant_id"}:
            args["page"] = int(page_token) if page_token else 1
        elif page_token is not None:
            raise ValueError("Freshteam reference pickers have no qualified cursor; use an exact custom value")
        if field_name in {"applicant_id", "field_name"}:
            args["job_id"] = (context or {}).get("job_id")
        config = FreshteamNodeConfig.model_validate({"credentials": credential_data, "config": args})
        authority = credential_data.get(_AUTH_KEY)
        if authority is not None and (not isinstance(authority, _Authority) or authority.credential != config.credentials):
            raise ValueError(_UNAVAILABLE)
        if authority is not None:
            await authority.require_current()
        node = cls(node_id="freshteam-picker", node_type="automation-freshteam", node_data={"config": args, "credentials": config.credentials.model_dump()}, config=config, sio=None, sid=None)
        if authority is not None:
            node.node_data.update({"credential_id": authority.credential_id, "_approval_pool": authority.pool})
            node.user_id, node.workflow_id, node.organization_id = authority.user_id, authority.workflow_id, authority.org_id
        result = await node.execute({})
        if authority is not None:
            await authority.require_current()
        rows = result["data"]["items"]
        if field_name == "field_name":
            rows = [row for row in rows if _custom_text(row)]
        return {"options": [{"value": row["name"] if field_name == "field_name" else str(row["id"]), "label": row.get("label") or row.get("title") or row.get("name") or " ".join(filter(None, (row.get("first_name"), row.get("last_name")))) or " ".join(filter(None, (row.get("candidate", {}).get("first_name"), row.get("candidate", {}).get("last_name")))) or str(row["id"])} for row in rows], "next_page_token": str(result["data"]["next_page"]) if result["data"].get("next_page") else None}
