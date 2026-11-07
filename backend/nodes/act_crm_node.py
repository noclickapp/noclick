"""Native Act! Web API records with issued JWT and credential-bound database."""
from __future__ import annotations

import ipaddress
import re
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import SSRFError, guarded_async_client

FAMILY = "act_crm_jwt"
MAX_BYTES = 2_000_000
RESOURCES = {"contact": "contacts", "company": "companies", "group": "groups", "opportunity": "opportunities", "activity": "Activities", "note": "notes"}


class ActCRMError(ValueError):
    def __init__(self, message, status_code=None, retry_after=None):
        super().__init__(message)
        self.status_code, self.retry_after = status_code, retry_after


def text(value, maximum=255):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Enter a nonempty value without edge whitespace or control characters")
    return value


def resource_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Enter the exact Act record ID without a URL or path")
    return value


def instance(value):
    raw = text(value, 1024)
    try:
        u = urlsplit(raw)
        port = u.port
        host = (u.hostname or "").lower()
        parts = u.path.rstrip("/").split("/")[1:]
        if (u.scheme != "https" or not host or u.username is not None or u.password is not None
                or u.query or u.fragment or "?" in raw or "#" in raw or "\\" in raw or "%" in raw
                or not parts or len(parts) > 8 or parts[-1].lower() != "act.web.api"
                or any(not re.fullmatch(r"[A-Za-z0-9_.~-]+", p) or p in {".", ".."} for p in parts)
                or (port is not None and not 1 <= port <= 65535)):
            raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError()
        except ValueError:
            if ":" in host or re.fullmatch(r"[0-9.]+", host):
                raise ValueError()
            if host in {"localhost", "metadata.google.internal"} or host.endswith((".localhost", ".local", ".internal")) or "." not in host:
                raise ValueError()
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or any(not p or p.startswith("-") or p.endswith("-") for p in host.split(".")):
                raise ValueError()
        # DNS and each socket dial are independently public-only and pinned.
        authority = f"[{host}]" if ":" in host else host
        return f"https://{authority}" + (f":{port}" if port and port != 443 else "") + "/" + "/".join(parts)
    except (ValueError, TypeError):
        raise ValueError("Enter a public HTTPS Act Web API base ending in /act.web.api; preserve its tenant path") from None


def guard(data, stored=False):
    if not isinstance(data, dict) or ((stored or "credential_type" in data) and data.get("credential_type") != FAMILY):
        raise ValueError("Select a native Act CRM issued JWT credential")


class ActCRMJWTCredential(BaseModel):
    model_config = ConfigDict(title="Act CRM JWT", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://www.act.com/developer/", "x-credential-instructions": "Use an already issued Act Web API JWT and its database. Enter the complete public HTTPS instance base including the cloud tenant path and /act.web.api. No login or token renewal is performed."})
    credential_type: Literal["act_crm_jwt"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    instance_url: str = Field(..., title="Web API Instance", description="For example https://your-host/your-tenant-api/act.web.api; never a contacts or authorize URL")
    database_name: str = Field(..., title="Act Database Name", description="Bound to this issued token; sent in Act-Database-Name")
    access_token: str = Field(..., title="Issued JWT", json_schema_extra={"ui:widget": "password"})

    @field_validator("instance_url", mode="before")
    @classmethod
    def base(cls, value):
        return instance(value)

    @field_validator("database_name", mode="before")
    @classmethod
    def database(cls, value):
        value = text(value, 128)
        if not value.isascii():
            raise ValueError("Enter an ASCII Act database header value")
        return value

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str) or len(value) > 16384 or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", value):
            raise ValueError("Paste the issued JWT without a Bearer prefix")
        return value


def credential(data):
    guard(data)
    try:
        return ActCRMJWTCredential.model_validate(data).model_dump(mode="json")
    except Exception:
        raise ValueError("Check the Act instance, database and issued JWT") from None


def picker(name, parent=None):
    options = {"field_name": name, "searchable": True, "allow_custom": True}
    if parent:
        options["depends_on"] = parent
    return {"x-dynamic-options": options}


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("contact_id", "company_id", "group_id", "opportunity_id", "activity_id", "note_id", "parent_group_id", mode="before", check_fields=False)
    @classmethod
    def identifiers(cls, value):
        return resource_id(value) if value is not None else None

    @field_validator("full_name", "first_name", "last_name", "job_title", "name", "industry", "division", "description", "source", "search", mode="before", check_fields=False)
    @classmethod
    def strings(cls, value):
        return text(value, 4096 if cls.__name__ in {"CreateGroup", "UpdateGroup"} else 255) if value is not None else None

    @field_validator("email_address", mode="before", check_fields=False)
    @classmethod
    def email(cls, value):
        if value is not None and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", text(value)):
            raise ValueError("Enter a contact email address")
        return value

    @field_validator("note_text", mode="before", check_fields=False)
    @classmethod
    def note(cls, value):
        if value is not None and (not isinstance(value, str) or not value or len(value) > 10000 or any(ord(c) < 32 and c not in "\n\r\t" for c in value)):
            raise ValueError("Enter a plain-text note of at most 10000 characters")
        return value


class Page(Config):
    top: int = Field(50, ge=1, le=100, strict=True, title="Page Limit", description="Local bounded OData $top; not a provider quota")
    skip: int = Field(0, ge=0, le=100000, strict=True, title="Rows to Skip", description="Documented OData $skip; no invented next link or stable snapshot")


class Write(Config):
    confirm_record_change: Literal[True] = Field(..., title="Confirm Record Change", description="Changes a real Act CRM record. Downstream automation and notifications are unverified.")


class ListContacts(Page):
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"x-display-name": "List Contacts"})


class Contact(Config):
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"x-display-name": "Get Contact"})
    contact_id: str = Field(..., json_schema_extra=picker("contact_id"))


class CreateContact(Write):
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"x-display-name": "Create Contact"})
    full_name: str
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    email_address: str | None = None
    company_id: str | None = Field(None, json_schema_extra=picker("company_id"))


class UpdateContact(Contact, Write):
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"x-display-name": "Update Contact"})
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    email_address: str | None = None
    company_id: str | None = Field(None, json_schema_extra=picker("company_id"))


class DeleteContact(Contact, Write):
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"x-display-name": "Delete Contact"})


class ListCompanies(Page):
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"x-display-name": "List Companies"})


class Company(Config):
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"x-display-name": "Get Company"})
    company_id: str = Field(..., json_schema_extra=picker("company_id"))


class CreateCompany(Write):
    operation: Literal["create_company"] = Field("create_company", json_schema_extra={"x-display-name": "Create Company"})
    name: str
    industry: str | None = None
    division: str | None = None


class UpdateCompany(Company, Write):
    operation: Literal["update_company"] = Field("update_company", json_schema_extra={"x-display-name": "Update Company"})
    name: str | None = None
    industry: str | None = None
    division: str | None = None


class DeleteCompany(Company, Write):
    operation: Literal["delete_company"] = Field("delete_company", json_schema_extra={"x-display-name": "Delete Company"})


class ListGroups(Page):
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"x-display-name": "List Groups"})


class Group(Config):
    operation: Literal["get_group"] = Field("get_group", json_schema_extra={"x-display-name": "Get Group"})
    group_id: str = Field(..., json_schema_extra=picker("group_id"))


class CreateGroup(Write):
    operation: Literal["create_group"] = Field("create_group", json_schema_extra={"x-display-name": "Create Group"})
    name: str
    description: str | None = None
    parent_group_id: str | None = Field(None, json_schema_extra=picker("group_id"))


class UpdateGroup(Group, Write):
    operation: Literal["update_group"] = Field("update_group", json_schema_extra={"x-display-name": "Update Group"})
    name: str | None = None
    description: str | None = None
    parent_group_id: str | None = Field(None, json_schema_extra=picker("group_id"))


class DeleteGroup(Group, Write):
    operation: Literal["delete_group"] = Field("delete_group", json_schema_extra={"x-display-name": "Delete Group"})


class ListOpportunities(Page):
    operation: Literal["list_opportunities"] = Field("list_opportunities", json_schema_extra={"x-display-name": "List Opportunities"})


class Opportunity(Config):
    operation: Literal["get_opportunity"] = Field("get_opportunity", json_schema_extra={"x-display-name": "Get Opportunity"})
    opportunity_id: str = Field(..., json_schema_extra=picker("opportunity_id"))


class CreateOpportunity(Write):
    operation: Literal["create_opportunity"] = Field("create_opportunity", json_schema_extra={"x-display-name": "Create Opportunity"})
    name: str
    source: str | None = None


class UpdateOpportunity(Opportunity, Write):
    operation: Literal["update_opportunity"] = Field("update_opportunity", json_schema_extra={"x-display-name": "Update Opportunity"})
    name: str | None = None
    source: str | None = None


class DeleteOpportunity(Opportunity, Write):
    operation: Literal["delete_opportunity"] = Field("delete_opportunity", json_schema_extra={"x-display-name": "Delete Opportunity"})


class ListActivities(Page):
    operation: Literal["list_activities"] = Field("list_activities")


class Activity(Config):
    operation: Literal["get_activity"] = Field("get_activity")
    activity_id: str = Field(..., json_schema_extra=picker("activity_id"))


class ListContactActivities(Page):
    operation: Literal["list_contact_activities"] = Field("list_contact_activities")
    contact_id: str = Field(..., json_schema_extra=picker("contact_id"))


class ListContactNotes(Page):
    operation: Literal["list_contact_notes"] = Field("list_contact_notes")
    contact_id: str = Field(..., json_schema_extra=picker("contact_id"))


class ListCompanyNotes(Page):
    operation: Literal["list_company_notes"] = Field("list_company_notes")
    company_id: str = Field(..., json_schema_extra=picker("company_id"))


class ListGroupNotes(Page):
    operation: Literal["list_group_notes"] = Field("list_group_notes")
    group_id: str = Field(..., json_schema_extra=picker("group_id"))


class ListOpportunityNotes(Page):
    operation: Literal["list_opportunity_notes"] = Field("list_opportunity_notes")
    opportunity_id: str = Field(..., json_schema_extra=picker("opportunity_id"))


class Note(Config):
    operation: Literal["get_note"] = Field("get_note")
    contact_id: str = Field(..., json_schema_extra=picker("contact_id"))
    note_id: str = Field(..., json_schema_extra=picker("note_id", "contact_id"))


class CreateNote(Write):
    operation: Literal["create_note"] = Field("create_note")
    contact_id: str = Field(..., json_schema_extra=picker("contact_id"))
    note_text: str = Field(..., json_schema_extra={"ui:widget": "textarea"})
    is_private: bool = True


class UpdateNote(Note, Write):
    operation: Literal["update_note"] = Field("update_note")
    note_text: str = Field(..., json_schema_extra={"ui:widget": "textarea"})


class DeleteNote(Note, Write):
    operation: Literal["delete_note"] = Field("delete_note")


ActCRMConfig = Annotated[Union[ListContacts, Contact, CreateContact, UpdateContact, DeleteContact, ListCompanies, Company, CreateCompany, UpdateCompany, DeleteCompany, ListGroups, Group, CreateGroup, UpdateGroup, DeleteGroup, ListOpportunities, Opportunity, CreateOpportunity, UpdateOpportunity, DeleteOpportunity, ListActivities, Activity, ListContactActivities, ListContactNotes, ListCompanyNotes, ListGroupNotes, ListOpportunityNotes, Note, CreateNote, UpdateNote, DeleteNote], Field(discriminator="operation")]


class ActCRMNodeConfig(NodeConfig[ActCRMConfig, ActCRMJWTCredential]):
    pass


async def freshen(data, **kwargs):
    if kwargs.get("credential_id"):
        if not kwargs.get("user_id"):
            raise ActCRMError("Current Act credential access requires an authenticated actor")
        from utils.credentials import resolve_credential_with_owner_fallback
        from utils.database_pool import get_native_pool
        pool = kwargs.get("pool")
        if pool is None:
            pool = get_native_pool()
        data = await resolve_credential_with_owner_fallback(
            kwargs["credential_id"], kwargs["user_id"], pool,
            org_id=kwargs.get("organization_id"), workflow_id=kwargs.get("workflow_id"))
        guard(data, stored=True)
    return credential(data)


async def request(data, method, route, *, query=None, body=None, expected=200, empty=False):
    guard(data, stored=True)
    try:
        async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=30) as client:
            response = await client.request(method, data["instance_url"] + "/api/" + route,
                headers={"Authorization": "Bearer " + data["access_token"], "Act-Database-Name": data["database_name"], "Accept": "application/json"}, params=query, json=body)
    except SSRFError:
        raise ActCRMError("Act instance must resolve to a public HTTPS destination") from None
    except httpx.RequestError:
        raise ActCRMError("Act could not be reached; the request is unverified") from None
    if response.status_code != expected:
        messages = {400: "request was invalid", 401: "issued token was refused or expired", 403: "permission or subscription was denied", 404: "record was not found", 429: "request limit was reached"}
        delay = response.headers.get("Retry-After")
        retry = int(delay) if delay and delay.isascii() and delay.isdecimal() and len(delay) <= 8 else None
        raise ActCRMError(f"Act HTTP {response.status_code}: {messages.get(response.status_code, 'response was not accepted')}", response.status_code, retry)
    if empty:
        if response.content:
            raise ActCRMError("Act returned content for a documented empty response")
        return None
    if len(response.content) > MAX_BYTES:
        raise ActCRMError("Act response exceeds the supported size")
    try:
        payload = response.json()
    except ValueError:
        raise ActCRMError("Act returned unreadable JSON") from None
    if not isinstance(payload, (dict, list)) or (isinstance(payload, dict) and any(k in payload for k in ("error", "errors"))):
        raise ActCRMError("Act returned an unreadable resource response")
    return payload


def safe_text(value, data):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value) or data["access_token"] in value:
        raise ActCRMError("Act returned unreadable or protected metadata")
    return value


def projection(raw, kind, data):
    if not isinstance(raw, dict):
        raise ActCRMError("Act returned unreadable record metadata")
    out = {"id": resource_id(raw.get("id"))}
    keys = {"contact": ("fullName", "firstName", "lastName", "company", "department", "jobTitle"),
        "company": ("name", "industry", "division"), "group": ("name",), "opportunity": ("name", "status", "source"),
        "activity": ("subject", "activityTypeName", "activityPriorityName", "startTime", "endTime"), "note": ("displayDate",)}[kind]
    for key in (*keys, "created", "edited"):
        if raw.get(key) is not None:
            out[key] = safe_text(raw[key], data)
    label = {"contact": "fullName", "company": "name", "group": "name", "opportunity": "name", "activity": "subject"}.get(kind)
    if label and not out.get(label):
        raise ActCRMError("Act returned unreadable record labels")
    if kind == "contact" and raw.get("companyID") not in (None, ""):
        out["companyID"] = resource_id(raw["companyID"])
    if kind == "group" and raw.get("parentID") not in (None, ""):
        out["parentID"] = resource_id(raw["parentID"])
    for key in ("isPrivate", "hasSubgroups", "isCleared"):
        if raw.get(key) is not None:
            if type(raw[key]) is not bool:
                raise ActCRMError("Act returned an unreadable metadata flag")
            out[key] = raw[key]
    if kind in {"note", "activity", "opportunity"}:
        for parent in ("contacts", "companies", "groups", "opportunities"):
            if raw.get(parent) is not None:
                if not isinstance(raw[parent], list) or len(raw[parent]) > 1000 or any(not isinstance(x, dict) for x in raw[parent]):
                    raise ActCRMError("Act returned unreadable record links")
                ids = [resource_id(x.get("id")) for x in raw[parent]]
                if len(set(ids)) != len(ids):
                    raise ActCRMError("Act returned duplicate record links")
                out[parent] = [{"id": i} for i in ids]
    return out


async def get_record(data, kind, identifier, contact_id=None):
    row = projection(await request(data, "GET", RESOURCES[kind] + "/" + identifier), kind, data)
    if row["id"] != identifier or (contact_id is not None and contact_id not in [x["id"] for x in row.get("contacts", [])]):
        raise ActCRMError("Act returned a different record or contact binding")
    return row


async def collection(data, route, kind, top=50, skip=0, query=None):
    payload = await request(data, "GET", route, query={"$top": top, "$skip": skip, **(query or {})})
    if not isinstance(payload, list) or len(payload) > top:
        raise ActCRMError("Act returned an unreadable or oversized bounded page")
    rows = [projection(x, kind, data) for x in payload]
    if len({x["id"] for x in rows}) != len(rows):
        raise ActCRMError("Act returned duplicate record identifiers")
    return {"items": rows, "requested_top": top, "requested_skip": skip, "has_more": None, "next_page_token": None}


class ActCRMNode(WorkflowNode):
    integration_type = "automation-act-crm"
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_companies", operation_arguments={"top": 3, "skip": 0}, noun="companies", label_keys=("name",), proves="account")
    edit_examples = ["List my Act contacts", "Create a company record", "Update an opportunity name", "Add a plain-text note to a contact"]

    @classmethod
    def get_config_model(cls):
        return ActCRMNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        try:
            if isinstance(config_data, dict) and config_data.get("credentials") is not None:
                guard(config_data["credentials"])
        except ValueError:
            raise ConfigValidationError("Select a native Act CRM issued JWT credential") from None
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if isinstance(config_data, dict) and config_data.get("credentials") is not None:
                guard(config_data["credentials"])
        except ValueError:
            return {"valid": False, "errors": ["Select a native Act CRM issued JWT credential"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    def _extract_actionable_validation_error(cls, error, config_data):
        return "Check the native Act instance, database, JWT and operation fields"

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await freshen(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def validate_credential(cls, data):
        try:
            data = await freshen(data)
            await collection(data, "companies", "company", top=1)
            return {"valid": True}
        except ActCRMError as exc:
            return {"valid": False if exc.status_code in {401, 403} else None, "error": str(exc)}
        except (ValueError, TypeError, KeyError):
            return {"valid": False, "error": "Check the Act instance, database and issued JWT"}

    @classmethod
    async def validate_credential_access(cls, data):
        return await cls.validate_credential(data)

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if page_token:
            raise ValueError("Act pickers show one bounded page; use explicit list top/skip or a manual record ID")
        data = await freshen(credential_data)
        kind = field_name.removesuffix("_id")
        if kind == "parent_group":
            kind = "group"
        if kind not in RESOURCES or not field_name.endswith("_id"):
            raise ValueError("Unknown native Act record picker")
        contact_id = resource_id((context or {}).get("contact_id")) if kind == "note" else None
        if contact_id:
            await get_record(data, "contact", contact_id)
        route = f"contacts/{contact_id}/notes" if kind == "note" else RESOURCES[kind]
        rows = (await collection(data, route, kind))["items"]
        if contact_id and any(contact_id not in [x["id"] for x in row.get("contacts", [])] for row in rows):
            raise ActCRMError("Act returned a different note contact binding")
        options = []
        for row in rows:
            label = row.get("name") or row.get("fullName") or row.get("subject") or row.get("displayDate") or row["id"]
            if not search or text(search).casefold() in label.casefold():
                options.append({"value": row["id"], "label": label})
        return {"options": options, "next_page_token": None}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a native Act CRM issued JWT credential")
        config = self.config.config
        try:
            nested = self.node_data.get("config") or {}
            cid = self.node_data.get("credential_id")
            if isinstance(nested, dict) and nested.get("credential_id"):
                if cid and cid != nested["credential_id"]:
                    raise ActCRMError("Act credential selection is ambiguous")
                cid = nested["credential_id"]
            data = await freshen(self.config.credentials.model_dump(mode="json"), credential_id=cid,
                pool=self.node_data.get("_approval_pool"), user_id=self.user_id,
                organization_id=self.organization_id, workflow_id=self.workflow_id)
            return {"status": "success", "action": config.operation, "data": await self._operation(data, config)}
        except ActCRMError as exc:
            return {"status": "error", "action": config.operation, "error": str(exc), "status_code": exc.status_code, "retry_after": exc.retry_after}
        except (ValueError, TypeError, KeyError):
            return {"status": "error", "action": config.operation, "error": "Act credential, authority or response could not be validated"}

    async def _operation(self, data, config):
        op = config.operation
        lists = {"list_contacts": "contact", "list_companies": "company", "list_groups": "group", "list_opportunities": "opportunity", "list_activities": "activity"}
        if op in lists:
            kind = lists[op]
            return await collection(data, RESOURCES[kind], kind, config.top, config.skip)
        if op.startswith("list_"):
            parent = op.split("_")[1]
            identifier = getattr(config, parent + "_id")
            await get_record(data, parent, identifier)
            kind = "activity" if op == "list_contact_activities" else "note"
            route = RESOURCES[parent].lower() + "/" + identifier + "/" + ("activities" if kind == "activity" else "notes")
            result = await collection(data, route, kind, config.top, config.skip)
            link = RESOURCES[parent]
            if any(identifier not in [x["id"] for x in row.get(link, [])] for row in result["items"]):
                raise ActCRMError("Act returned a different parent record binding")
            return result
        action, kind = op.split("_", 1)
        route = RESOURCES[kind]
        identifier = getattr(config, kind + "_id", None) if action != "create" else None
        contact_id = getattr(config, "contact_id", None) if kind == "note" else None
        if identifier:
            row = await get_record(data, kind, identifier, contact_id)
            if action == "get":
                return row
        if action == "delete":
            await request(data, "DELETE", route + "/" + identifier, expected=204, empty=True)
            return {"id": identifier, "deletion_request_completed": True, "verified_readback": None}
        if contact_id:
            await get_record(data, "contact", contact_id)
        company_id = getattr(config, "company_id", None) if kind == "contact" else None
        if company_id:
            await get_record(data, "company", company_id)
        parent_group = getattr(config, "parent_group_id", None)
        if parent_group:
            await get_record(data, "group", parent_group)
        fields = {"contact": {"full_name": "fullName", "first_name": "firstName", "last_name": "lastName", "job_title": "jobTitle", "email_address": "emailAddress", "company_id": "companyID"},
            "company": {"name": "name", "industry": "industry", "division": "division"}, "group": {"name": "name", "description": "description", "parent_group_id": "parentID"},
            "opportunity": {"name": "name", "source": "source"}, "note": {"note_text": "noteText"}}[kind]
        body = {target: getattr(config, key) for key, target in fields.items() if getattr(config, key, None) is not None}
        if not body:
            raise ActCRMError("Choose at least one documented record field to update")
        if kind == "opportunity" and action == "create":
            body["status"] = "Open"
        if kind == "note" and action == "create":
            body.update(contacts=[{"id": contact_id}], isPrivate=config.is_private)
        result = projection(await request(data, "POST" if action == "create" else "PATCH", route if action == "create" else route + "/" + identifier,
            body=body, query={"format": "text"} if kind == "note" else None, expected=201 if action == "create" else 200), kind, data)
        if (identifier and result["id"] != identifier) or (company_id and result.get("companyID") != company_id) or (parent_group and result.get("parentID") != parent_group) or (contact_id and contact_id not in [x["id"] for x in result.get("contacts", [])]):
            raise ActCRMError("Act returned a different changed record or parent binding")
        return {"resource": result, "write_acknowledged": True, "verified_readback": None}
