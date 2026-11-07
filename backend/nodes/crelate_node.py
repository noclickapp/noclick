"""Crelate API3 recruiting metadata and explicit ordinary CRM record management.

The supplied user key stays in X-Api-Key. Native operations use closed fields,
current stored authority and projected responses; no employment or sending API.
"""
import base64
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import parse_qsl, quote, urljoin, urlsplit

import httpx
from opentelemetry import propagate
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, field_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import load_paginated_options, normalize_search
from utils.credentials import resolve_credential_with_owner_fallback
from utils.outbound_trace_privacy import OutboundTraceProvider
from utils.ssrf import assert_exact_url_origin, guarded_async_client

ORIGIN, BASE = "https://app.crelate.com", "https://app.crelate.com/api3"
FAMILY = "crelate_api_key"
GUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
PRIVATE_REQUEST = ContextVar("crelate_private_http_request", default=None)


class _RequestFilter(logging.Filter):
    def filter(self, record):
        if PRIVATE_REQUEST.get() is None:
            return True
        record.msg, record.args = "Crelate HTTP transport activity", ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _RequestFilter()


def _install_privacy():
    names = {"httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"}
    names.update(n for n in tuple(logging.Logger.manager.loggerDict) if n.startswith(("httpx.", "httpcore.")))
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(GUID, value.lower()) or value == "00000000-0000-0000-0000-000000000000":
        raise ValueError("Enter a nonempty Crelate GUID")
    return value.lower()


Identifier = Annotated[str, BeforeValidator(_id), Field(json_schema_extra={"format": "uuid", "pattern": "^" + GUID + "$"})]
Text = Annotated[str, Field(min_length=1, max_length=255)]


def _family(raw):
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    if not isinstance(raw, dict) or ("credential_type" in raw and raw["credential_type"] != FAMILY):
        raise ValueError("Connect a native Crelate credential")
    return raw


class CrelateAPIKeyCredential(BaseModel):
    credential_type: Literal["crelate_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="User API Key", description="Current API3 X-Api-Key header. Never put the key in a URL.", json_schema_extra={"ui:widget": "password"})
    expected_organization_name: Optional[Text] = Field(None, title="Expected Organization Unique Name", description="Name from organizations/self; distinct from DisplayName. Optional binding, not an organization GUID.")
    expected_user_id: Optional[Identifier] = Field(None, title="Expected Current User GUID")
    model_config = ConfigDict(title="Crelate API Key", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://help.crelate.com/en/articles/4120535-find-and-manage-your-api-key"})

    @field_validator("api_key")
    @classmethod
    def header_value(cls, value):
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply a valid Crelate API key")
        return value


def _credential(raw):
    raw = _family(raw)
    try:
        return CrelateAPIKeyCredential.model_validate(raw)
    except Exception:
        raise ValueError("Crelate credential is invalid; reconnect") from None


def _op(value, title, group):
    return Field(value, title=title, json_schema_extra={"const": value, "ui:hidden": True, "x-category": group, "x-display-name": title, "x-is-trigger": False})


def _selector(title, name):
    return Field(..., title=title, json_schema_extra={"ui:widget": "select", "ui:options": {"loadOptions": True, "dependsOn": []}, "x-resource-type": "crelate_" + name})


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetSelf(Settings):
    operation: Literal["get_self"] = _op("get_self", "Get Current User and Organization", "Account")


class GetOrganization(Settings):
    operation: Literal["get_organization"] = _op("get_organization", "Get Organization Metadata", "Account")


class ContactInfo(Settings):
    operation: Literal["contact_info"] = _op("contact_info", "Get Contact Field Metadata", "Metadata")


class CompanyInfo(Settings):
    operation: Literal["company_info"] = _op("company_info", "Get Company Field Metadata", "Metadata")


class JobInfo(Settings):
    operation: Literal["job_info"] = _op("job_info", "Get Job Field Metadata", "Metadata")


class Page(Settings):
    page_token: Optional[str] = Field(None, max_length=30000, title="Continuation", json_schema_extra={"ui:hidden": True})
    limit: int = Field(25, ge=1, le=100, title="Page Size")
    modified_after: Optional[datetime] = Field(None, title="Modified After", description="UTC incremental-sync window. Offset walks can shift under concurrent changes.")

    @field_validator("modified_after")
    @classmethod
    def aware(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Supply a timestamp with its timezone")
        return value


class ListContacts(Page):
    operation: Literal["list_contacts"] = _op("list_contacts", "List Contact Metadata", "Contacts")


class GetContact(Settings):
    operation: Literal["get_contact"] = _op("get_contact", "Get Contact Metadata", "Contacts")
    contact_id: Identifier = _selector("Contact", "contact_id")


class CreateContact(Settings):
    operation: Literal["create_contact"] = _op("create_contact", "Create Contact", "Contacts")
    first_name: Text = Field(..., title="First Name")
    last_name: Text = Field(..., title="Last Name")
    external_primary_key: Optional[Text] = Field(None, title="External Primary Key", description="Not guaranteed unique; not an idempotency key.")


class UpdateContact(GetContact):
    operation: Literal["update_contact"] = _op("update_contact", "Rename Own Contact", "Contacts")
    first_name: Text = Field(..., title="First Name")
    last_name: Text = Field(..., title="Last Name")


class DeleteContact(GetContact):
    operation: Literal["delete_contact"] = _op("delete_contact", "Delete Own Contact", "Contacts")


class ListCompanies(Page):
    operation: Literal["list_companies"] = _op("list_companies", "List Company Metadata", "Companies")


class GetCompany(Settings):
    operation: Literal["get_company"] = _op("get_company", "Get Company Metadata", "Companies")
    company_id: Identifier = _selector("Company", "company_id")


class CreateCompany(Settings):
    operation: Literal["create_company"] = _op("create_company", "Create Company", "Companies")
    name: Text = Field(..., title="Company Name")
    external_primary_key: Optional[Text] = Field(None, title="External Primary Key", description="Not guaranteed unique.")


class UpdateCompany(GetCompany):
    operation: Literal["update_company"] = _op("update_company", "Rename Own Company", "Companies")
    name: Text = Field(..., title="Company Name")


class DeleteCompany(GetCompany):
    operation: Literal["delete_company"] = _op("delete_company", "Delete Own Company", "Companies")


class ListJobs(Page):
    operation: Literal["list_jobs"] = _op("list_jobs", "List Company Job Metadata", "Jobs")
    company_id: Identifier = _selector("Company", "company_id")


class GetJob(GetCompany):
    operation: Literal["get_job"] = _op("get_job", "Get Company Job Metadata", "Jobs")
    job_id: Identifier = Field(..., title="Job GUID", json_schema_extra={"x-resource-type": "crelate_job_id"})


class CreateJob(GetCompany):
    operation: Literal["create_job"] = _op("create_job", "Create Company Job Record", "Jobs")
    name: Text = Field(..., title="Job Name", description="Ordinary CRM job creation. No publication, placement or employment endpoint is used; automation effects require later qualification.")
    external_primary_key: Optional[Text] = Field(None, title="External Primary Key", description="Not guaranteed unique.")


class UpdateJob(GetJob):
    operation: Literal["update_job"] = _op("update_job", "Rename Own Company Job", "Jobs")
    name: Text = Field(..., title="Job Name")


class DeleteJob(GetJob):
    operation: Literal["delete_job"] = _op("delete_job", "Delete Own Company Job", "Jobs")


class ContactParent(Settings):
    contact_id: Identifier = _selector("Parent Contact", "contact_id")
    parent_entity_name: Text = Field(..., title="Exact Parent Entity Name", description="Supply the exact Crelate LookupAny EntityName for your contact. The public schema does not enumerate this value. It is never used as an API route.")


class ListNotes(ContactParent, Page):
    operation: Literal["list_notes"] = _op("list_notes", "List Contact Note Metadata", "Notes")


class GetNote(ContactParent):
    operation: Literal["get_note"] = _op("get_note", "Get Contact Note Metadata", "Notes")
    note_id: Identifier = Field(..., title="Note GUID", json_schema_extra={"x-resource-type": "crelate_note_id"})


class CreateNote(ContactParent):
    operation: Literal["create_note"] = _op("create_note", "Create Plain Contact Note", "Notes")
    display: str = Field(..., min_length=1, max_length=10000, title="Plain Note", json_schema_extra={"ui:widget": "textarea"})


class UpdateNote(GetNote):
    operation: Literal["update_note"] = _op("update_note", "Update Own Plain Contact Note", "Notes")
    display: str = Field(..., min_length=1, max_length=10000, title="Plain Note", json_schema_extra={"ui:widget": "textarea"})


class DeleteNote(GetNote):
    operation: Literal["delete_note"] = _op("delete_note", "Delete Own Contact Note", "Notes")


class ListTasks(ContactParent, Page):
    operation: Literal["list_tasks"] = _op("list_tasks", "List Own Contact Task Metadata", "Tasks")


class GetTask(ContactParent):
    operation: Literal["get_task"] = _op("get_task", "Get Own Contact Task Metadata", "Tasks")
    task_id: Identifier = Field(..., title="Task GUID", json_schema_extra={"x-resource-type": "crelate_task_id"})


class CreateTask(ContactParent):
    operation: Literal["create_task"] = _op("create_task", "Create Own Contact Task", "Tasks")
    display: str = Field(..., min_length=1, max_length=10000, title="Plain Task", json_schema_extra={"ui:widget": "textarea"})
    when: datetime = Field(..., title="Scheduled Time", description="Required documented task When, sent in UTC.")

    @field_validator("when")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Supply a scheduled time with its timezone")
        return value


class UpdateTask(GetTask):
    operation: Literal["update_task"] = _op("update_task", "Update Own Contact Task", "Tasks")
    display: str = Field(..., min_length=1, max_length=10000, title="Plain Task", json_schema_extra={"ui:widget": "textarea"})
    when: datetime = Field(..., title="Scheduled Time")

    @field_validator("when")
    @classmethod
    def aware(cls, value):
        return CreateTask.aware(value)


class DeleteTask(GetTask):
    operation: Literal["delete_task"] = _op("delete_task", "Delete Own Contact Task", "Tasks")


Operations = Annotated[Union[GetSelf, GetOrganization, ContactInfo, CompanyInfo, JobInfo,
    ListContacts, GetContact, CreateContact, UpdateContact, DeleteContact,
    ListCompanies, GetCompany, CreateCompany, UpdateCompany, DeleteCompany,
    ListJobs, GetJob, CreateJob, UpdateJob, DeleteJob,
    ListNotes, GetNote, CreateNote, UpdateNote, DeleteNote,
    ListTasks, GetTask, CreateTask, UpdateTask, DeleteTask], Field(discriminator="operation")]


class CrelateNodeConfig(NodeConfig[Operations, CrelateAPIKeyCredential]):
    pass


class CrelateCredentialSnapshot(dict):
    """Credential data plus node-local context for the field-options refresh hook."""


class _Authority:
    def __init__(self, credential, *, credential_id=None, user_id=None, pool=None, organization_id=None, workflow_id=None):
        self.credential = _credential(credential)
        self.credential_id, self.user_id, self.pool = credential_id, user_id, pool
        self.organization_id, self.workflow_id = organization_id, workflow_id

    async def check(self):
        _credential(self.credential)
        if not self.credential_id:
            return
        if not self.user_id:
            raise ValueError("Crelate saved credential requires an authorized actor")
        row = await resolve_credential_with_owner_fallback(self.credential_id, self.user_id, self.pool,
            org_id=self.organization_id, workflow_id=self.workflow_id)
        if not row:
            raise ValueError("Crelate current credential is unavailable or revoked")
        if _credential(row).model_dump() != self.credential.model_dump():
            raise ValueError("Crelate credential binding changed; reconnect")


def _secrets(credential):
    key = credential.api_key
    return {key, quote(key, safe=""), base64.b64encode(key.encode()).decode(), base64.urlsafe_b64encode(key.encode()).decode(), key.encode().hex()}


def _public(value, credential):
    secrets = _secrets(credential)
    if any(s in json.dumps(value, ensure_ascii=False) for s in secrets):
        raise ValueError("Crelate response contained protected credential data")
    return value


COMMON = ("Id", "CreatedById", "CreatedOn", "ModifiedOn", "Owners")
PUBLIC = {
    "contacts": COMMON + ("FirstName", "LastName", "Name", "ExternalPrimaryKey"),
    "companies": COMMON + ("Name", "ExternalPrimaryKey"),
    "jobs": COMMON + ("Name", "AccountId", "ExternalPrimaryKey", "IsPublishedToFreeBoards"),
    "notes": COMMON + ("ParentId", "Announced", "IsEngagement", "IsReachOut", "When"),
    "tasks": COMMON + ("ParentId", "Announced", "When"),
}
WRITE = {"contacts": {"FirstName", "LastName", "Owners", "ExternalPrimaryKey"},
    "companies": {"Name", "Owners", "ExternalPrimaryKey"}, "jobs": {"Name", "AccountId", "Owners", "ExternalPrimaryKey"},
    "notes": {"Display", "ParentId", "IsEngagement", "IsReachOut"}, "tasks": {"Display", "ParentId", "Owners", "When"}}


def _lookup(value, *, any_entity=False, owner=False):
    if not isinstance(value, dict):
        raise ValueError("Crelate lookup metadata is invalid")
    result = {"Id": _id(value.get("Id"))}
    if any_entity:
        if not isinstance(value.get("EntityName"), str) or not 1 <= len(value["EntityName"]) <= 255:
            raise ValueError("Crelate parent entity evidence is missing")
        result["EntityName"] = value["EntityName"]
    if owner:
        if type(value.get("IsPrimary")) is not bool:
            raise ValueError("Crelate primary-owner metadata is invalid")
        result["IsPrimary"] = value["IsPrimary"]
    return result


def _project(kind, row, credential):
    if not isinstance(row, dict):
        raise ValueError("Crelate resource metadata is invalid")
    result = {"Id": _id(row.get("Id"))}
    for k in PUBLIC[kind][1:]:
        if k not in row:
            continue
        value = row[k]
        if value is None:
            result[k] = None
        elif k in {"CreatedById", "AccountId", "ParentId"}:
            result[k] = _lookup(value, any_entity=k == "ParentId")
        elif k == "Owners":
            if not isinstance(value, list) or len(value) > 100:
                raise ValueError("Crelate owner metadata is invalid")
            result[k] = [_lookup(v, owner=True) for v in value]
        elif k in {"Announced", "IsEngagement", "IsReachOut", "IsPublishedToFreeBoards"}:
            if type(value) is not bool:
                raise ValueError("Crelate boolean metadata is invalid")
            result[k] = value
        elif not isinstance(value, str) or len(value) > 10000:
            raise ValueError("Crelate textual metadata is invalid")
        else:
            result[k] = value
    return _public(result, credential)


class CrelateRequestError(ValueError):
    def __init__(self, message, *, status=None, retry_after=None, outcome="unverified"):
        super().__init__(message)
        self.status, self.retry_after, self.outcome = status, retry_after, outcome


class _Client:
    def __init__(self, authority):
        self.authority, self.credential = authority, authority.credential
        self.user_id, self.organization_name = None, None

    async def request(self, method, path, *, params=None, body=None):
        roots = set(PUBLIC)
        valid = method == "GET" and path in {"/users/self", "/organizations/self", "/contacts/info", "/companies/info", "/jobs/info"}
        valid = valid or method in {"GET", "POST"} and path in {"/" + k for k in roots}
        valid = valid or method in {"GET", "PATCH", "DELETE"} and re.fullmatch(r"/(?:contacts|companies|jobs|notes|tasks)/" + GUID, path)
        if not valid:
            raise ValueError("Unsupported Crelate native route")
        kind = path.split("/")[1]
        params = {"validation": "strict", **(params or {})}
        allowed = {"validation"} if method != "GET" or path.endswith(("/self", "/info")) else {"validation", "fields", "unmask_values", "total_count", "limit", "offset", "sort_by", "modified_after", "company_ids", "parent_id", "owner_id"}
        if set(params) - allowed or params["validation"] != "strict" or "unmask_values" in params and params["unmask_values"] != "false":
            raise ValueError("Unsupported Crelate native query")
        if kind in PUBLIC and method == "GET" and not path.endswith("/info") and params.get("fields") != ",".join(PUBLIC[kind]):
            raise ValueError("Crelate reads require the native metadata projection")
        if body is not None:
            if method not in {"POST", "PATCH"} or not isinstance(body, dict) or set(body) != {"entity"} or not isinstance(body["entity"], dict) or not body["entity"] or set(body["entity"]) - WRITE[kind] or not self.user_id:
                raise ValueError("Unsupported Crelate native payload")
            if method == "PATCH" and set(body["entity"]) & {"ParentId", "Owners", "ExternalPrimaryKey", "AccountId"}:
                raise ValueError("Crelate native updates do not reparent or transfer ownership")
            _public(body, self.credential)
        elif method in {"POST", "PATCH"}:
            raise ValueError("Crelate native payload is required")
        _public(params, self.credential)
        await self.authority.check()
        headers = {"X-Api-Key": self.credential.api_key, "Accept": "application/json", "Content-Type": "application/json"}
        url = BASE + path
        assert_exact_url_origin(url, ORIGIN)
        _install_privacy()
        private = PRIVATE_REQUEST.set(True)
        try:
            with OutboundTraceProvider().get_tracer(__name__).start_as_current_span(method, kind=SpanKind.CLIENT,
                    attributes={"http.request.method": method, "url.full": BASE + "/[native-resource]", "url.scheme": "https", "server.address": "app.crelate.com", "server.port": 443},
                    record_exception=False, set_status_on_exception=False) as span:
                try:
                    propagate.inject(headers)
                    with suppress_http_instrumentation():
                        async with guarded_async_client(follow_redirects=False, trust_env=False, timeout=httpx.Timeout(20)) as client:
                            async with client.stream(method, url, headers=headers, params=params, json=body) as response:
                                content = bytearray()
                                async for chunk in response.aiter_bytes():
                                    if len(content) + len(chunk) > 2_000_000:
                                        raise CrelateRequestError("Crelate metadata response exceeds its bound; verify any write")
                                    content.extend(chunk)
                                status, media = response.status_code, response.headers.get("content-type", "")
                                span.set_attribute("http.response.status_code", status)
                except BaseException as error:
                    span.set_status(StatusCode.ERROR)
                    if isinstance(error, httpx.HTTPError):
                        raise CrelateRequestError("Crelate write outcome is unknown; verify before retrying" if method != "GET" else "Crelate request could not be read; access is unverified") from None
                    raise
        finally:
            PRIVATE_REQUEST.reset(private)
        await self.authority.check()
        try:
            payload = json.loads(content) if media.split(";", 1)[0].strip().lower() == "application/json" else None
        except Exception:
            payload = None
        if status == 429:
            delay = payload.get("retry_after_seconds") if isinstance(payload, dict) else None
            delay = int(delay) if type(delay) is int or isinstance(delay, str) and re.fullmatch(r"[0-9]{1,6}", delay) else None
            delay = delay if delay is not None and 0 <= delay <= 86400 else None
            raise CrelateRequestError("Crelate rate limit reached; wait before retrying", status=429, retry_after=delay, outcome="rate_limited")
        if status not in ({200, 206} if method == "GET" else {200}):
            raise CrelateRequestError(f"Crelate returned HTTP {status}; check access or organization field requirements and verify any uncertain write", status=status)
        if not isinstance(payload, dict) or not {"Data", "Errors", "Metadata"} <= set(payload) or not isinstance(payload["Metadata"], dict) or not isinstance(payload["Errors"], list) or len(payload["Errors"]) > 100:
            raise CrelateRequestError("Crelate response envelope is invalid; verify any write before retrying", status=status)
        errors = []
        for error in payload["Errors"]:
            if not isinstance(error, dict) or type(error.get("Code")) is not int or error["Code"] < 100 or error["Code"] > 599 or not isinstance(error.get("Type"), str):
                raise CrelateRequestError("Crelate error envelope is invalid; outcome is unverified")
            errors.append({"code": error["Code"], "type": error["Type"] if error["Type"] in {"IgnoredParameter", "IgnoredField"} else "ProviderError"})
        failed = any(e["code"] >= 300 for e in errors)
        if status == 200 and failed or status == 206 and not failed:
            raise CrelateRequestError("Crelate response status and errors are inconsistent; verify outcome")
        if method != "GET" and errors:
            raise CrelateRequestError("Crelate reported ignored native write fields; verify outcome before retrying", status=status)
        return {"Data": payload["Data"], "Metadata": payload["Metadata"], "errors": errors, "outcome": "partial" if status == 206 else "success"}

    async def identity(self):
        user = (await self.request("GET", "/users/self"))["Data"]
        org = (await self.request("GET", "/organizations/self"))["Data"]
        if not isinstance(user, dict) or not isinstance(user.get("FullName"), str) or not user["FullName"] or len(user["FullName"]) > 255 or not isinstance(org, dict) or not isinstance(org.get("Name"), str) or not org["Name"] or len(org["Name"]) > 255:
            raise ValueError("Crelate current user/organization evidence is missing")
        self.user_id, self.organization_name = _id(user.get("Id")), org["Name"]
        c = self.credential
        if c.expected_user_id and c.expected_user_id != self.user_id or c.expected_organization_name and c.expected_organization_name != self.organization_name:
            raise ValueError("Crelate key belongs to another user or organization")
        result = {"user_id": self.user_id, "user_name": user["FullName"], "organization_name": self.organization_name}
        if isinstance(org.get("DisplayName"), str) and len(org["DisplayName"]) <= 255:
            result["organization_display_name"] = org["DisplayName"]
        return _public(result, c)

    async def one(self, kind, identifier, parent=None):
        payload = await self.request("GET", "/" + kind + "/" + identifier, params={"fields": ",".join(PUBLIC[kind]), "unmask_values": "false"})
        data = _project(kind, payload["Data"], self.credential)
        if data["Id"] != identifier:
            raise ValueError("Crelate selected record changed identity")
        self.parent(kind, data, parent)
        return data

    def parent(self, kind, data, parent):
        if parent is not None and (data.get("AccountId") if kind == "jobs" else data.get("ParentId")) != parent:
            raise ValueError("Crelate record belongs to another parent")

    def owned(self, kind, data):
        if data.get("CreatedById") != {"Id": self.user_id}:
            raise ValueError("Manage only records created by the current Crelate user")
        if kind == "tasks" and data.get("Owners") != [{"Id": self.user_id, "IsPrimary": True}]:
            raise ValueError("Manage only a task solely owned by the current Crelate user")

    async def info(self, kind):
        payload = await self.request("GET", "/" + kind + "/info")
        data = payload["Data"]
        if not isinstance(data, dict) or not isinstance(data.get("Fields"), dict) or len(data["Fields"]) > 500:
            raise ValueError("Crelate field metadata is invalid")
        result = {}
        for name, entry in data["Fields"].items():
            if not isinstance(name, str) or len(name) > 255 or not isinstance(entry, dict) or not isinstance(entry.get("DisplayName"), str) or len(entry["DisplayName"]) > 255 or not isinstance(entry.get("Type"), str) or len(entry["Type"]) > 100 or type(entry.get("IsEncrypted")) is not bool or not isinstance(entry.get("ValidFor"), list) or any(v not in {"create", "read", "update", "sort"} for v in entry["ValidFor"]) or type(entry.get("ValueMaskingMode")) is not int or entry["ValueMaskingMode"] not in {0, 1, 2}:
                raise ValueError("Crelate field metadata is incomplete")
            result[name] = {k: entry[k] for k in ("DisplayName", "Type", "IsEncrypted", "ValidFor", "ValueMaskingMode")}
        return _public(result, self.credential)

    def _scope(self, kind, params):
        return hashlib.sha256(json.dumps([FAMILY, self.user_id, self.organization_name, kind, params], sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _encode(self, kind, params, offset, seen):
        blob = json.dumps({"scope": self._scope(kind, params), "offset": offset, "seen": seen}, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(blob).decode().rstrip("=") + "." + hmac.new(self.credential.api_key.encode(), blob, hashlib.sha256).hexdigest()

    def _decode(self, kind, params, token):
        try:
            encoded, signature = token.split(".")
            blob = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
            data = json.loads(blob)
            if not hmac.compare_digest(signature, hmac.new(self.credential.api_key.encode(), blob, hashlib.sha256).hexdigest()) or set(data) != {"scope", "offset", "seen"} or data["scope"] != self._scope(kind, params) or type(data["offset"]) is not int or not 1 <= data["offset"] <= 1_000_000 or not isinstance(data["seen"], list) or not 1 <= len(data["seen"]) < 100 or any(not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v) for v in data["seen"]):
                raise ValueError
            return data["offset"], data["seen"]
        except Exception:
            raise ValueError("Crelate continuation belongs to another key, user, organization, resource or query") from None

    def _next(self, kind, params, metadata, offset):
        if metadata.get("MoreRecords") is not None and type(metadata["MoreRecords"]) is not bool:
            raise ValueError("Crelate MoreRecords metadata is invalid")
        links = metadata.get("Links")
        if links is not None and not isinstance(links, dict):
            raise ValueError("Crelate paging links are invalid")
        next_link = (links or {}).get("Next")
        if next_link is None:
            if metadata.get("MoreRecords") is True:
                raise ValueError("Crelate reports more records without a Next link")
            return None
        if not isinstance(next_link, dict) or set(next_link) - {"Href"}:
            raise ValueError("Crelate Next link is invalid")
        href = next_link.get("Href")
        if href is None or href == "":
            if metadata.get("MoreRecords") is True:
                raise ValueError("Crelate reports more records without a Next URL")
            return None
        if not isinstance(href, str) or len(href) > 10000 or any(ord(c) < 33 or ord(c) == 127 for c in href):
            raise ValueError("Crelate Next URL is invalid")
        url = urljoin(BASE + "/" + kind, href)
        assert_exact_url_origin(url, ORIGIN)
        split = urlsplit(url)
        pairs = parse_qsl(split.query, keep_blank_values=True, strict_parsing=True)
        query = dict(pairs)
        expected = {"validation": "strict", **{k: str(v) for k, v in params.items()}}
        if split.path != "/api3/" + kind or split.fragment or split.username or split.password or len(pairs) != len(query) or set(query) != set(expected) | {"offset"} or any(query.get(k) != v for k, v in expected.items()) or not re.fullmatch(r"[0-9]{1,7}", query.get("offset", "")):
            raise ValueError("Crelate Next URL changed resource, query or protected projection")
        target = int(query["offset"])
        if not offset < target <= 1_000_000 or metadata.get("MoreRecords") is False:
            raise ValueError("Crelate Next URL repeated or contradicted the current page")
        return target

    async def page(self, kind, params, token=None, parent=None):
        offset, seen = self._decode(kind, params, token) if token else (0, [])
        payload = await self.request("GET", "/" + kind, params={**params, "offset": offset})
        rows, metadata = payload["Data"], payload["Metadata"]
        if not isinstance(rows, list) or len(rows) > params["limit"]:
            raise ValueError("Crelate collection exceeds its bound or has an invalid shape")
        data = [_project(kind, row, self.credential) for row in rows]
        if len({r["Id"] for r in data}) != len(data):
            raise ValueError("Crelate page repeated a resource")
        for row in data:
            self.parent(kind, row, parent)
            if kind == "tasks" and row.get("Owners") != [{"Id": self.user_id, "IsPrimary": True}]:
                raise ValueError("Crelate own-task collection changed its owner scope")
        fingerprint = hashlib.sha256(json.dumps(sorted(r["Id"] for r in data)).encode()).hexdigest()
        if rows and fingerprint in seen:
            raise ValueError("Crelate pagination repeated a page")
        target = self._next(kind, params, metadata, offset)
        if target is not None and (not rows or len(seen) >= 99):
            raise ValueError("Crelate continuation exceeds its bound or follows an empty page")
        total = metadata.get("TotalRecords")
        if total is not None and (type(total) is not int or total < 0):
            raise ValueError("Crelate total count is invalid")
        return {"data": data, "next_page_token": self._encode(kind, params, target, seen + [fingerprint]) if target is not None else None,
            "total": total, "outcome": payload["outcome"], "errors": payload["errors"]}


class CrelateNode(WorkflowNode):
    integration_type = "automation-crelate"
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(noun="organization user", operation="get_self", identity_operation="get_self", identity_keys=("user_name", "organization_name"), proves="account")

    @classmethod
    def get_config_model(cls):
        return CrelateNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if raw is not None:
            _family(raw)
        try:
            data = runtime_config_view(config_data, CrelateNodeConfig)
            TypeAdapter(Operations).validate_python(data["config"])
            if raw is not None:
                data["credentials"] = _credential(raw).model_dump()
        except Exception:
            raise ValueError("Crelate configuration is invalid; check typed operation fields") from None
        return super().parse_config(data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if config_data.get("credentials") is not None:
                _credential(config_data["credentials"])
            return super().validate_config(config_data)
        except Exception:
            return {"valid": False, "errors": ["Crelate credential or configuration is invalid"], "satisfied_set": None}

    def _authority(self):
        return _Authority(self.config.credentials, credential_id=self.node_data.get("credential_id"), user_id=self.user_id,
            pool=self.node_data.get("_approval_pool"), organization_id=self.organization_id, workflow_id=self.workflow_id)

    async def run(self, inputs):
        if self.node_data.get("credentials") is not None:
            _family(self.node_data["credentials"])
        self._native_authority = self._authority()
        await self._native_authority.check()
        return await super().run(inputs)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # The field-options loader adds row metadata alongside the decrypted
        # credential. Validate only the credential fields, then recheck the
        # current accessible row through the native authority boundary.
        credential = _credential({k: v for k, v in _family(credential_data).items()
            if k not in {"token_version", "updated_at"}})
        authority = _Authority(credential, credential_id=credential_id, user_id=user_id, pool=pool)
        await authority.check()
        result = CrelateCredentialSnapshot(credential.model_dump())
        result.authority = authority
        return result

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        _credential(credential_data)
        return {"valid": None, "error": "Run current user/organization connection evidence to verify access"}

    async def execute(self, inputs):
        if self.node_data.get("credentials") is not None:
            _family(self.node_data["credentials"])
        client = _Client(getattr(self, "_native_authority", None) or self._authority())
        identity = await client.identity()
        cfg, op = self.config.config, self.config.config.operation
        if op in {"get_self", "get_organization"}:
            return identity if op == "get_self" else {k: v for k, v in identity.items() if k.startswith("organization_")}
        if op.endswith("_info"):
            kind = {"contact_info": "contacts", "company_info": "companies", "job_info": "jobs"}[op]
            return {**identity, "fields": await client.info(kind), "required_fields": None, "custom_fields_supported_for_writes": False}
        kind = "contacts" if op.endswith(("contact", "contacts")) else "companies" if op.endswith(("company", "companies")) else "jobs" if op.endswith(("job", "jobs")) else "notes" if op.endswith(("note", "notes")) else "tasks"
        action = op.split("_", 1)[0]
        parent = None
        if kind == "jobs":
            await client.one("companies", cfg.company_id)
            parent = {"Id": cfg.company_id}
        if kind in {"notes", "tasks"}:
            await client.one("contacts", cfg.contact_id)
            parent = {"Id": cfg.contact_id, "EntityName": cfg.parent_entity_name}
        if action == "list":
            params = {"limit": cfg.limit, "fields": ",".join(PUBLIC[kind]), "unmask_values": "false", "total_count": "true", "sort_by": "ModifiedOn asc"}
            if cfg.modified_after:
                params["modified_after"] = cfg.modified_after.astimezone(timezone.utc).isoformat()
            if kind == "jobs":
                params["company_ids"] = cfg.company_id
            elif parent:
                params["parent_id"] = cfg.contact_id
            if kind == "tasks":
                params["owner_id"] = client.user_id
            return {**identity, **await client.page(kind, params, cfg.page_token, parent)}
        target = getattr(cfg, {"contacts": "contact_id", "companies": "company_id", "jobs": "job_id", "notes": "note_id", "tasks": "task_id"}[kind], None) if action != "create" else None
        row = await client.one(kind, target, parent) if target else None
        if action == "get":
            if kind == "tasks":
                client.owned(kind, row)
            return {**identity, "data": row}
        if row:
            client.owned(kind, row)
        if action == "delete":
            receipt = await client.request("DELETE", "/" + kind + "/" + target)
            if receipt["Data"] is not True:
                raise ValueError("Crelate delete receipt is not true; verify before retrying")
            return {**identity, "id": target, "deleted": True, "effect": "Permanent CRM deletion accepted; independent authenticated absence readback is required"}
        if kind == "contacts":
            entity = {"FirstName": cfg.first_name, "LastName": cfg.last_name}
        elif kind in {"companies", "jobs"}:
            entity = {"Name": cfg.name}
            if kind == "jobs" and action == "create":
                entity["AccountId"] = parent
        else:
            entity = {"Display": cfg.display}
            if action == "create":
                entity["ParentId"] = parent
            if kind == "notes":
                entity.update(IsEngagement=False, IsReachOut=False)
            else:
                entity["When"] = cfg.when.astimezone(timezone.utc).isoformat()
        if action == "create" and kind in {"contacts", "companies", "jobs", "tasks"}:
            entity["Owners"] = [{"Id": client.user_id, "IsPrimary": True}]
        if kind in {"contacts", "companies", "jobs"}:
            metadata = await client.info(kind)
            mode = "create" if action == "create" else "update"
            if any(k not in metadata or mode not in metadata[k]["ValidFor"] or metadata[k]["IsEncrypted"] or metadata[k]["ValueMaskingMode"] != 0 for k in entity):
                raise ValueError("Crelate organization does not permit the native writable fields")
            if action == "create" and cfg.external_primary_key:
                entry = metadata.get("ExternalPrimaryKey")
                if entry is None or "create" not in entry["ValidFor"] or entry["IsEncrypted"] or entry["ValueMaskingMode"] != 0:
                    raise ValueError("Crelate external primary key field is unavailable")
                entity["ExternalPrimaryKey"] = cfg.external_primary_key
        receipt = await client.request("POST" if action == "create" else "PATCH", "/" + kind + ("/" + target if target else ""), body={"entity": entity})
        if action == "create":
            target = _id(receipt["Data"])
        elif receipt["Data"] is not True:
            raise ValueError("Crelate update receipt is not true; verify before retrying")
        # Readback is separate from the GUID/boolean acknowledgement. Plain
        # note/task content stays private and is not exported as node output.
        changed = await client.one(kind, target, parent)
        client.owned(kind, changed)
        for name in ({"FirstName", "LastName"} if kind == "contacts" else {"Name"} if kind in {"companies", "jobs"} else set()):
            if changed.get(name) != entity[name]:
                raise ValueError("Crelate write readback differs; verify before retrying")
        return {**identity, "id": target, "data": changed, "acknowledged": True, "effect": "Ordinary recruiting CRM record changed; organization automation/notification effects are not qualified"}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name not in {"contact_id", "company_id"}:
            raise ValueError("Unsupported Crelate selector")
        _credential(credential_data)
        authority = getattr(credential_data, "authority", None)
        if authority is None:
            raise ValueError("Load Crelate selectors through the admitted credential loader")
        client = _Client(authority)
        await client.identity()
        kind = "contacts" if field_name == "contact_id" else "companies"
        params = {"limit": 50, "fields": ",".join(PUBLIC[kind]), "unmask_values": "false", "total_count": "true", "sort_by": "ModifiedOn asc"}
        async def fetch(token):
            page = await client.page(kind, params, token)
            if page["outcome"] != "success" or page["errors"]:
                raise ValueError("Crelate selectors require a complete successful provider page")
            return [{"value": r["Id"], "label": r.get("Name") or " ".join(v for v in (r.get("FirstName"), r.get("LastName")) if v) or r["Id"]} for r in page["data"]], page["next_page_token"]
        return await load_paginated_options(fetch, page_token=page_token, search=normalize_search(search), cap=1000)
