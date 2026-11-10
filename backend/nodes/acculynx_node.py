"""Native AccuLynx V2 location-bound CRM metadata and documented management.

Issued API keys use the published Bearer contract, with a verified company
binding before every operation. Closed routes preserve empty write responses
and keep purchasing, payments, messages and assignments outside this node.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.acculynx.com/api/v2"
FAMILY = "acculynx_api_key"


def _uuid(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value) or UUID(value).int == 0:
        raise ValueError("Use a nonempty record UUID")
    return str(UUID(value))


def _text(value):
    if not isinstance(value, str) or not value.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("Use nonempty text without control characters")
    return value


def _note(value):
    if not isinstance(value, str) or not value.strip() or any((ord(ch) < 32 and ch not in "\n\r\t") or ord(ch) == 127 for ch in value):
        raise ValueError("Use nonempty note text without unsupported control characters")
    return value


RecordId = Annotated[str, BeforeValidator(_uuid), Field(pattern=r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")]
Name = Annotated[str, BeforeValidator(_text), Field(min_length=1, max_length=250)]
Index = Annotated[int, Field(strict=True, ge=0, le=1000000)]
Size = Annotated[int, Field(strict=True, ge=1, le=25)]


def _op(name, label, category, *, write=False):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label,
                 "x-category": category, "x-is-trigger": False, "x-read-only": not write})


def _pick(field):
    return {"x-dynamic-options": {"field_name": field, "searchable": True, "allow_custom": True},
            "x-resource-type": field.removesuffix("_id")}


class AccuLynxAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://apidocs.acculynx.com/docs/authentication"})
    credential_type: Literal["acculynx_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, min_length=1, max_length=4096,
                         description="Already-issued active location API key; sent as Authorization: Bearer. No token mint or expiry is invented.",
                         json_schema_extra={"ui:widget": "password"})
    company_id: RecordId = Field(..., title="Bound Company ID", description="Existing company UUID returned by company-settings for this location key. Every operation verifies it; this does not prove access to other locations.")

    @field_validator("api_key")
    @classmethod
    def secret(cls, value):
        if not value.isascii() or any(ord(ch) < 33 or ord(ch) > 126 for ch in value):
            raise ValueError("Use the issued API key without whitespace or control characters")
        return value


class CRMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(CRMConfig):
    start_index: Index = Field(0, title="First Record Index", description="Zero-based record index. The exact endpoint query name is supplied by the native operation.")
    page_size: Size = Field(25, title="Page Size", description="One page, at most 25 records. Jobs has a documented server maximum of 25.")


class Company(CRMConfig):
    operation: Literal["get_company_settings"] = _op("get_company_settings", "Get Bound Company Settings", "Company")


class Contacts(Page):
    operation: Literal["list_contacts"] = _op("list_contacts", "List Contacts", "Contacts")


class Contact(CRMConfig):
    operation: Literal["get_contact"] = _op("get_contact", "Get Contact", "Contacts")
    contact_id: RecordId = Field(..., title="Contact", json_schema_extra=_pick("contact_id"))


class ContactTypes(Page):
    operation: Literal["list_contact_types"] = _op("list_contact_types", "List Contact Types", "Contacts")


class Change(CRMConfig):
    confirm_crm_change: Literal[True] = Field(..., title="Confirm CRM Change", description="Changes real company CRM records and can activate company workflows. Quiet behavior and rollback are not guaranteed.")

    @field_validator("confirm_crm_change", mode="before")
    @classmethod
    def acknowledge(cls, value):
        if value is not True:
            raise ValueError("Confirm this CRM change explicitly")
        return value


class CreateContact(Change):
    operation: Literal["create_contact"] = _op("create_contact", "Create Contact", "Contacts", write=True)
    first_name: Name = Field(..., title="First Name")
    last_name: Name = Field(..., title="Last Name")
    contact_type_id: RecordId = Field(..., title="Contact Type", json_schema_extra=_pick("contact_type_id"))
    company_name: Name | None = Field(None, title="Contact Company Name")
    cross_reference: Name | None = Field(None, title="External Reference")


class ContactNote(Change):
    operation: Literal["create_contact_note"] = _op("create_contact_note", "Create Contact Note", "Contacts", write=True)
    contact_id: RecordId = Field(..., title="Contact", json_schema_extra=_pick("contact_id"))
    note: Annotated[str, BeforeValidator(_note), Field(min_length=1, max_length=1000)] = Field(..., title="Note", json_schema_extra={"ui:widget": "textarea"})


class Jobs(Page):
    operation: Literal["list_jobs"] = _op("list_jobs", "List Jobs", "Jobs")
    assignment: Literal["assigned", "unassigned"] | None = Field(None, title="Assignment", description="Omit for all jobs; unassigned leads are included through the list route.")
    milestones: list[Literal["lead", "prospect", "approved", "completed", "invoiced", "closed", "cancelled"]] = Field(default_factory=list, max_length=7)
    start_date: date | None = None
    end_date: date | None = None
    date_filter_type: Literal["CreatedDate", "MilestoneDate", "ModifiedDate"] = "CreatedDate"
    sort_by: Literal["CreatedDate", "MilestoneDate", "ModifiedDate"] = "CreatedDate"
    sort_order: Literal["Ascending", "Descending"] = "Ascending"

    @model_validator(mode="after")
    def dates(self):
        if (self.start_date is None) != (self.end_date is None) or (self.start_date and self.start_date >= self.end_date):
            raise ValueError("Provide both inclusive date boundaries with start earlier than end")
        if "cancelled" in self.milestones and self.assignment != "unassigned":
            raise ValueError("Cancelled jobs require unassigned filtering")
        return self


class Leads(Page):
    operation: Literal["list_unassigned_leads"] = _op("list_unassigned_leads", "List Unassigned Leads", "Leads")


class Job(CRMConfig):
    operation: Literal["get_job"] = _op("get_job", "Get Assigned Job", "Jobs")
    job_id: RecordId = Field(..., title="Job", description="Single-job GET excludes unassigned leads. Use List Unassigned Leads for newly created leads.", json_schema_extra=_pick("job_id"))


class CreateLead(Change):
    operation: Literal["create_unassigned_lead"] = _op("create_unassigned_lead", "Create Unassigned Lead", "Leads", write=True)
    contact_id: RecordId = Field(..., title="Primary Contact", json_schema_extra=_pick("contact_id"))
    notes: Annotated[str, BeforeValidator(_note), Field(min_length=1, max_length=1000)] | None = Field(None, title="Lead Notes", json_schema_extra={"ui:widget": "textarea"})


class Milestones(CRMConfig):
    operation: Literal["list_milestones"] = _op("list_milestones", "List Workflow Milestones", "Milestones")


class CurrentMilestone(Job):
    operation: Literal["get_current_job_milestone"] = _op("get_current_job_milestone", "Get Current Job Milestone", "Milestones")


class LeadHistory(CRMConfig):
    operation: Literal["get_lead_history"] = _op("get_lead_history", "Get Lead History", "Leads")
    lead_id: RecordId = Field(..., title="Lead", json_schema_extra=_pick("lead_id"))


class LeadSources(Page):
    operation: Literal["list_lead_sources"] = _op("list_lead_sources", "List Active Lead Sources", "Company")


class Priority(Change):
    operation: Literal["update_job_priority"] = _op("update_job_priority", "Update Job Priority", "Jobs", write=True)
    job_id: RecordId = Field(..., title="Job", json_schema_extra=_pick("job_id"))
    priority: Literal["Normal", "High", "Urgent"] = Field(..., title="Priority")


class LeadSource(Change):
    operation: Literal["update_job_lead_source"] = _op("update_job_lead_source", "Update Job Lead Source", "Jobs", write=True)
    job_id: RecordId = Field(..., title="Job", json_schema_extra=_pick("job_id"))
    lead_source_id: RecordId = Field(..., title="Lead Source", json_schema_extra=_pick("lead_source_id"))


AccuLynxOperation = Annotated[Union[Company, Contacts, Contact, ContactTypes, CreateContact, ContactNote,
                        Jobs, Leads, Job, CreateLead, Milestones, CurrentMilestone, LeadHistory,
                        LeadSources, Priority, LeadSource], Field(discriminator="operation")]


class AccuLynxNodeConfig(NodeConfig[AccuLynxOperation, AccuLynxAPIKeyCredential]):
    pass


class AccuLynxError(Exception):
    def __init__(self, message, status_code=None, uncertain=False):
        super().__init__(message)
        self.status_code, self.uncertain = status_code, uncertain


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("Duplicate response key")
        out[key] = value
    return out


def _finite(value, depth=0):
    if depth > 40 or isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Invalid response value")
    if isinstance(value, dict):
        for item in value.values():
            _finite(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _finite(item, depth + 1)


class CRMSession:
    def __init__(self, credential):
        self.credential = credential

    def redact(self, value):
        if isinstance(value, str):
            return value.replace("Bearer " + self.credential.api_key, "[redacted]").replace(self.credential.api_key, "[redacted]")
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, dict):
            return {self.redact(key): self.redact(item) for key, item in value.items()}
        return value

    async def request(self, method, path, *, params=None, body=None):
        # Every reachable native route has a fixed method, query and body shape.
        identifier = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
        read = path in {"company-settings", "contacts", "contacts/contact-types", "jobs",
                           "company-settings/job-file-settings/workflow-milestones", "company-settings/leads/lead-sources"} or re.fullmatch(rf"(?:contacts|jobs)/{identifier}|jobs/{identifier}/milestones/current|leads/{identifier}/history|company-settings/leads/lead-sources/{identifier}", path)
        allowed_body = {"contacts": {"firstName", "lastName", "contactTypeIds", "companyName", "crossReference"}, "jobs": {"contact", "notes"}} if method == "POST" else {}
        if method == "POST" and re.fullmatch(rf"contacts/{identifier}/notes", path):
            allowed_body[path] = {"note"}
        if method == "PUT" and re.fullmatch(rf"jobs/{identifier}/priority", path):
            allowed_body[path] = {"priority"}
        if method == "PUT" and re.fullmatch(rf"jobs/{identifier}/lead-source", path):
            allowed_body[path] = {"id"}
        valid = method == "GET" and read and body is None or method in {"POST", "PUT"} and path in allowed_body and isinstance(body, dict) and set(body) <= allowed_body[path] and not params
        query = {"pageSize", "pageStartIndex", "assignment", "milestones", "startDate", "endDate", "dateFilterType", "sortBy", "sortOrder"} if path == "jobs" else {"pageSize", "recordStartIndex"} if path == "company-settings/leads/lead-sources" else {"pageSize", "pageStartIndex"} if path in {"contacts", "contacts/contact-types"} else set()
        if not valid or params and not set(params) <= query:
            raise AccuLynxError("Unsupported native AccuLynx request")
        mutation, status = method != "GET", None
        expected = 200 if method == "GET" else 201 if method == "POST" else 204
        empty = method == "PUT" or method == "POST" and path.endswith("/notes")
        try:
            async with guarded_async_client(timeout=20, trust_env=False, follow_redirects=False) as client:
                async with client.stream(method, BASE_URL + "/" + path, params=params,
                                         headers={"Authorization": "Bearer " + self.credential.api_key, "Accept": "application/json"}, json=body) as response:
                    status = response.status_code
                    if status != expected:
                        raise AccuLynxError("AccuLynx refused the request" if status in {400, 401, 403, 404, 416, 429} else "AccuLynx returned an unexpected HTTP status", status, mutation)
                    chunks, length = [], 0
                    async for chunk in response.aiter_bytes():
                        length += len(chunk)
                        if length > 2 * 1024 * 1024:
                            raise AccuLynxError("AccuLynx response exceeds the native limit", status, mutation)
                        chunks.append(chunk)
                    payload = b"".join(chunks)
                    if empty:
                        if payload:
                            raise AccuLynxError("AccuLynx returned an unexpected acknowledgement body", status, mutation)
                        return None, status
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise AccuLynxError("AccuLynx returned unverified response media", status, mutation)
                    data = json.loads(payload, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    _finite(data)
                    if not isinstance(data, dict) or any(key in data for key in ("error", "errors", "detail", "traceId")) or data.get("success") is False or data.get("executed") is False or data.get("pending") is True or data.get("rejected") is True or data.get("halt") is True or "status" in data and data["status"] not in {"success", "ok"}:
                        raise AccuLynxError("AccuLynx returned an unverified response envelope", status, mutation)
                    if "status_code" in data and data["status_code"] != status:
                        raise AccuLynxError("AccuLynx returned an unverified response envelope", status, mutation)
                    return data, status
        except AccuLynxError:
            raise
        except (httpx.HTTPError, OSError):
            raise AccuLynxError("AccuLynx request could not be verified; no automatic retry", status, mutation) from None
        except Exception:
            raise AccuLynxError("AccuLynx returned unverified JSON metadata", status, mutation) from None

    def record(self, data, kind, status=200, expected=None):
        if not isinstance(data, dict):
            raise AccuLynxError("AccuLynx returned unverified record metadata", status)
        try:
            identifier = data.get("companyId") if kind == "company" else data.get("id")
            if kind == "milestones":
                if type(identifier) is not int or identifier < 1:
                    raise ValueError
            else:
                identifier = _uuid(identifier)
            if expected is not None and identifier != expected:
                raise ValueError
            out = {"companyId" if kind == "company" else "id": identifier}
            keys = {"company": ("name",), "contacts": ("firstName", "lastName", "companyName", "crossReference", "createdDate", "modifiedDate"),
                    "jobs": ("jobName", "jobNumber", "currentMilestone", "priority", "milestoneDate", "createdDate", "modifiedDate"),
                    "types": ("name",), "sources": ("name",), "milestones": ("name",), "current": ("name",)}[kind]
            for key in keys:
                if key in data and data[key] is not None:
                    if not isinstance(data[key], str) or len(data[key]) > 2000:
                        raise ValueError
                    out[key] = data[key]
            if kind in {"company", "types", "sources", "milestones", "current"} and not out.get("name", "").strip():
                raise ValueError
            if kind == "company":
                if "hasInsurance" in data:
                    if type(data["hasInsurance"]) is not bool:
                        raise ValueError
                    out["hasInsurance"] = data["hasInsurance"]
                if data.get("timeZoneInfo") is not None:
                    zone = data["timeZoneInfo"]
                    if not isinstance(zone, dict):
                        raise ValueError
                    out["timeZoneInfo"] = {}
                    for key in ("name", "daylightName", "baseUtcOffset", "adjustedUtcOffset"):
                        if key in zone:
                            if not isinstance(zone[key], str) or len(zone[key]) > 250:
                                raise ValueError
                            out["timeZoneInfo"][key] = zone[key]
                    if "supportsDaylightSavingTime" in zone:
                        if type(zone["supportsDaylightSavingTime"]) is not bool:
                            raise ValueError
                        out["timeZoneInfo"]["supportsDaylightSavingTime"] = zone["supportsDaylightSavingTime"]
            if kind == "types" and "isDefault" in data:
                if type(data["isDefault"]) is not bool:
                    raise ValueError
                out["isDefault"] = data["isDefault"]
            if kind == "current" and "isCurrent" in data:
                if data["isCurrent"] is not True:
                    raise ValueError
                out["isCurrent"] = True
            if kind == "jobs":
                if "priority" in out and out["priority"] not in {"Normal", "High", "Urgent"}:
                    raise ValueError
                if "currentMilestone" in out and out["currentMilestone"] not in {"Lead", "Prospect", "Approved", "Completed", "Invoiced", "Closed", "Cancelled"}:
                    raise ValueError
                for key in ("leadSource", "jobCategory", "workType"):
                    if data.get(key) is not None:
                        item = data[key]
                        if not isinstance(item, dict):
                            raise ValueError
                        item_id = _uuid(item.get("id")) if key == "leadSource" else item.get("id")
                        if key != "leadSource" and (type(item_id) is not int or item_id < 1):
                            raise ValueError
                        out[key] = {"id": item_id}
                        if isinstance(item.get("name"), str) and len(item["name"]) <= 2000:
                            out[key]["name"] = item["name"]
            return out
        except Exception:
            raise AccuLynxError("AccuLynx returned unverified record metadata", status) from None

    async def company(self):
        data, status = await self.request("GET", "company-settings")
        return self.record(data, "company", status, self.credential.company_id), status

    def page(self, data, kind, start, size, status=200):
        rows = data.get("items")
        count, actual_size, actual_start = data.get("count"), data.get("pageSize"), data.get("pageStartIndex")
        if not isinstance(rows, list) or len(rows) > size or any(type(value) is not int for value in (count, actual_size, actual_start)) or count < 0 or actual_size != size or actual_start != start or count < start + len(rows) or not rows and count > start:
            raise AccuLynxError("AccuLynx returned unverified collection paging", status)
        result = [self.record(row, kind, status) for row in rows]
        if len({row["id"] for row in result}) != len(result):
            raise AccuLynxError("AccuLynx returned duplicate record IDs", status)
        next_index = start + len(rows) if start + len(rows) < count else None
        return {"items": result, "count": count, "page_size": size, "start_index": start,
                "next_start_index": next_index, "continuation_verified": True, "snapshot_verified": False}

    async def get_record(self, kind, identifier):
        path = "company-settings/leads/lead-sources/" + identifier if kind == "sources" else kind + "/" + identifier
        data, status = await self.request("GET", path)
        return self.record(data, kind, status, identifier), status


OPERATIONS = ("get_company_settings", "list_contacts", "get_contact", "list_contact_types", "create_contact",
              "create_contact_note", "list_jobs", "list_unassigned_leads", "get_job", "create_unassigned_lead",
              "list_milestones", "get_current_job_milestone", "get_lead_history", "list_lead_sources",
              "update_job_priority", "update_job_lead_source")


class AccuLynxNode(WorkflowNode):
    integration_type = "automation-acculynx"
    credential_provider_labels = {"acculynx": "Acculynx Account"}
    scope_registry = ScopeRegistry("acculynx", {name: ScopeRequirement(credential_types=(FAMILY,), note="Issued key permissions and API access belong to the company location; no OAuth scopes are documented.") for name in OPERATIONS})
    connection_evidence = ConnectionEvidence(operation="get_company_settings", noun="companies", label_keys=("name", "companyId"))

    @classmethod
    def get_config_model(cls):
        return AccuLynxNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        credential = config_data.get("credentials")
        if isinstance(credential, dict) and credential.get("credential_type") not in (None, FAMILY):
            raise ValueError("Use current AccuLynx API-key credentials")
        return super().parse_config(config_data)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        try:
            session = CRMSession(AccuLynxAPIKeyCredential.model_validate(credential_data))
            row, _ = await session.company()
            return {"valid": True, "name": session.redact(row["name"])}
        except AccuLynxError as error:
            return {"valid": False if error.status_code in {401, 403} else None, "name": None, "error": str(error), "status_code": error.status_code}
        except Exception:
            return {"valid": False, "name": None, "error": "Use a valid AccuLynx API key and company binding"}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        routes = {"contact_id": ("contacts", "contacts", "pageStartIndex"), "contact_type_id": ("contacts/contact-types", "types", "pageStartIndex"),
                  "job_id": ("jobs", "jobs", "pageStartIndex"), "lead_id": ("jobs", "jobs", "pageStartIndex"),
                  "lead_source_id": ("company-settings/leads/lead-sources", "sources", "recordStartIndex")}
        if field_name not in routes:
            return {"options": [], "next_page_token": None}
        if page_token is not None and (not isinstance(page_token, str) or not re.fullmatch(r"0|[1-9][0-9]{0,6}", page_token) or int(page_token) > 1000000):
            raise ValueError("Use the returned local record-index token")
        start = int(page_token) if page_token is not None else 0
        session = CRMSession(AccuLynxAPIKeyCredential.model_validate(credential_data))
        await session.company()
        path, kind, index_name = routes[field_name]
        params = {index_name: start, "pageSize": 25}
        if field_name == "job_id":
            params["assignment"] = "assigned"
        elif field_name == "lead_id":
            params.update(assignment="unassigned", milestones="lead")
        data, status = await session.request("GET", path, params=params)
        page = session.page(data, kind, start, 25, status)
        options = []
        for row in page["items"]:
            label = " ".join(filter(None, (row.get("firstName"), row.get("lastName")))) if kind == "contacts" else row.get("jobName") if kind == "jobs" else row.get("name")
            label = label or row.get("companyName") or row.get("jobNumber") or row["id"]
            if not search or search.casefold() in label.casefold():
                options.append({"value": row["id"], "label": label})
        return session.redact({"options": options, "next_page_token": str(page["next_start_index"]) if page["next_start_index"] is not None else None})

    async def execute(self, inputs):
        if not isinstance(self.config, AccuLynxNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect current AccuLynx API-key credentials")
        config, session = self.config.config, CRMSession(self.config.credentials)
        status, mutation = None, False
        try:
            company, status = await session.company()
            if isinstance(config, Company):
                output = {"companies": [company]}
            elif isinstance(config, (Contacts, ContactTypes, Jobs, Leads, LeadSources)):
                kind = "contacts" if isinstance(config, Contacts) else "types" if isinstance(config, ContactTypes) else "sources" if isinstance(config, LeadSources) else "jobs"
                path = "contacts" if kind == "contacts" else "contacts/contact-types" if kind == "types" else "company-settings/leads/lead-sources" if kind == "sources" else "jobs"
                params = {"pageSize": config.page_size, "recordStartIndex" if kind == "sources" else "pageStartIndex": config.start_index}
                if isinstance(config, Jobs):
                    params.update(dateFilterType=config.date_filter_type, sortBy=config.sort_by, sortOrder=config.sort_order)
                    if config.assignment:
                        params["assignment"] = config.assignment
                    if config.milestones:
                        params["milestones"] = ",".join(config.milestones)
                    if config.start_date:
                        params.update(startDate=config.start_date.isoformat(), endDate=config.end_date.isoformat())
                elif isinstance(config, Leads):
                    params.update(assignment="unassigned", milestones="lead")
                data, status = await session.request("GET", path, params=params)
                output = session.page(data, kind, config.start_index, config.page_size, status)
            elif isinstance(config, Contact):
                row, status = await session.get_record("contacts", config.contact_id)
                output = {"contact": row}
            elif isinstance(config, CurrentMilestone):
                await session.get_record("jobs", config.job_id)
                data, status = await session.request("GET", f"jobs/{config.job_id}/milestones/current")
                output = {"milestone": session.record(data, "current", status)}
            elif isinstance(config, Job):
                row, status = await session.get_record("jobs", config.job_id)
                output = {"job": row}
            elif isinstance(config, Milestones):
                data, status = await session.request("GET", "company-settings/job-file-settings/workflow-milestones")
                rows = data.get("items")
                if not isinstance(rows, list) or len(rows) > 100:
                    raise AccuLynxError("AccuLynx returned unverified milestone metadata", status)
                items = [session.record(row, "milestones", status) for row in rows]
                if len({row["id"] for row in items}) != len(items):
                    raise AccuLynxError("AccuLynx returned duplicate milestones", status)
                output = {"milestones": items}
            elif isinstance(config, LeadHistory):
                data, status = await session.request("GET", f"leads/{config.lead_id}/history")
                rows = data.get("items")
                if not isinstance(rows, list) or len(rows) > 1000 or any(not isinstance(row, dict) or not isinstance(row.get("action"), str) or not isinstance(row.get("date"), str) for row in rows):
                    raise AccuLynxError("AccuLynx returned unverified lead history", status)
                output = {"lead_id": config.lead_id, "history": [{key: row[key] for key in ("action", "date")} for row in rows]}
            else:
                method, body = "POST", None
                identifier, path = None, None
                if isinstance(config, CreateContact):
                    data, status = await session.request("GET", "contacts/contact-types", params={"pageStartIndex": 0, "pageSize": 25})
                    types = session.page(data, "types", 0, 25, status)
                    if config.contact_type_id not in {row["id"] for row in types["items"]}:
                        raise AccuLynxError("Contact type was not verified in the bounded current-company page", status)
                    path, body = "contacts", {"firstName": config.first_name, "lastName": config.last_name, "contactTypeIds": [config.contact_type_id]}
                    if config.company_name is not None:
                        body["companyName"] = config.company_name
                    if config.cross_reference is not None:
                        body["crossReference"] = config.cross_reference
                elif isinstance(config, (ContactNote, CreateLead)):
                    await session.get_record("contacts", config.contact_id)
                    if isinstance(config, ContactNote):
                        identifier, path, body = config.contact_id, f"contacts/{config.contact_id}/notes", {"note": config.note}
                    else:
                        path, body = "jobs", {"contact": {"id": config.contact_id}}
                        if config.notes is not None:
                            body["notes"] = config.notes
                elif isinstance(config, (Priority, LeadSource)):
                    await session.get_record("jobs", config.job_id)
                    identifier, method = config.job_id, "PUT"
                    if isinstance(config, Priority):
                        path, body = f"jobs/{identifier}/priority", {"priority": config.priority}
                    else:
                        await session.get_record("sources", config.lead_source_id)
                        path, body = f"jobs/{identifier}/lead-source", {"id": config.lead_source_id}
                if path is None:
                    raise ValueError
                mutation = True
                data, status = await session.request(method, path, body=body)
                if isinstance(config, (CreateContact, CreateLead)):
                    identifier = _uuid(data.get("id"))
                output = {"record_id": identifier, "company_id": session.credential.company_id, "status_code": status,
                          "provider_acknowledged": True, "readback_verified": False}
                if isinstance(config, ContactNote):
                    output.update(contact_id=config.contact_id, note_id=None)
                if isinstance(config, CreateLead):
                    output.update(created_as="unassigned_lead", get_job_readback_supported=False)
            return session.redact({"status": "success", **output})
        except AccuLynxError as error:
            return {"status": "error", "error": str(error), "status_code": error.status_code, "uncertain_outcome": error.uncertain}
        except Exception:
            return {"status": "error", "error": "AccuLynx returned unverified CRM metadata", "status_code": status, "uncertain_outcome": mutation}
