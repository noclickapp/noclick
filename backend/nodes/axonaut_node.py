"""Native Axonaut v2 CRM and project management; no financial or sending API."""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.credentials import resolve_credential_with_owner_fallback

FAMILY = "axonaut_api_key"
ORIGIN = "https://axonaut.com"
PREFIX = "/api/v2/"
MAX_BYTES = 2_000_000


class AxonautError(ValueError):
    def __init__(self, message, status_code=None, retry_after=None):
        super().__init__(message)
        self.status_code, self.retry_after = status_code, retry_after


def text(value, maximum=255):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Enter a nonempty value without edge whitespace or control characters")
    return value


def resource_id(value):
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError("Enter a positive resource ID")
    return value


def picker(name, parent=None):
    spec = {"field_name": name, "searchable": True, "allow_custom": True}
    if parent:
        spec["depends_on"] = parent
    return {"x-dynamic-options": spec}


def guard(data, stored=False):
    if not isinstance(data, dict) or ((stored or "credential_type" in data) and data.get("credential_type") != FAMILY):
        raise ValueError("Select a native Axonaut API key")


class AxonautAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Axonaut API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://axonaut.com/api/v2/doc",
            "x-credential-instructions": "Copy your key from Axonaut's wrench menu > API. It is sent unchanged in the userApiKey header; no Bearer prefix or account query is used."})
    credential_type: Literal["axonaut_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = text(value, 8192)
        if any(c.isspace() for c in value) or not value.isascii() or value.startswith(("http:", "https:")):
            raise ValueError("Paste the Axonaut API key without an authentication prefix")
        return value


def credential(data):
    guard(data)
    try:
        return AxonautAPIKeyCredential.model_validate(data).model_dump(mode="json")
    except Exception:
        raise ValueError("Check the native Axonaut API key") from None


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("company_id", "contact_id", "opportunity_id", "task_id", "project_id",
        "parent_project_id", "task_status_id", "task_nature_id", "project_nature_id", mode="before", check_fields=False)
    @classmethod
    def ids(cls, value):
        return resource_id(value) if value is not None else None

    @field_validator("name", "title", "number", "search", "internal_id", "firstname", "lastname",
        "pipe_name", "pipe_step_name", mode="before", check_fields=False)
    @classmethod
    def strings(cls, value):
        return text(value) if value is not None else None

    @field_validator("email", mode="before", check_fields=False)
    @classmethod
    def email_address(cls, value):
        if value is not None and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", text(value)):
            raise ValueError("Enter a valid contact email address")
        return value


class Page(Config):
    page: int | None = Field(None, ge=0, le=100000, strict=True,
        description="Optional documented page HEADER. Omit for the provider default. The API specification does not define a page size or continuation marker.")


class Write(Config):
    confirm_management_write: Literal[True] = Field(..., title="Confirm Record Change",
        description="Changes a real CRM/project record; configured downstream effects and notifications are unverified")


class Account(Config):
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"x-display-name": "Get Current Account"})


class ListCompanies(Page):
    operation: Literal["list_companies"] = Field("list_companies", json_schema_extra={"x-display-name": "List Companies"})
    search: str | None = None
    internal_id: str | None = None
    company_type: Literal["customer", "prospect", "supplier", "all"] = "all"


class Company(Config):
    operation: Literal["get_company"] = Field("get_company", json_schema_extra={"x-display-name": "Get Company"})
    company_id: int = Field(..., json_schema_extra=picker("company_id"))


class CreateCompany(Write):
    operation: Literal["create_company"] = Field("create_company", json_schema_extra={"x-display-name": "Create Company"})
    name: str
    internal_id: str | None = None
    is_prospect: bool = True
    is_customer: bool = False


class UpdateCompany(Company, Write):
    operation: Literal["update_company"] = Field("update_company", json_schema_extra={"x-display-name": "Update Company"})
    name: str | None = None
    internal_id: str | None = None


class DeleteCompany(Company, Write):
    operation: Literal["delete_company"] = Field("delete_company", json_schema_extra={"x-display-name": "Request Company Deletion"})


class ListContacts(Page):
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"x-display-name": "List Company Contacts"})
    company_id: int | None = Field(None, json_schema_extra=picker("company_id"))
    firstname: str | None = None
    lastname: str | None = None


class Contact(Config):
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"x-display-name": "Get Company Contact"})
    company_id: int = Field(..., json_schema_extra=picker("company_id"))
    contact_id: int = Field(..., json_schema_extra=picker("contact_id", "company_id"))


class CreateContact(Write):
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"x-display-name": "Create Company Contact"})
    company_id: int = Field(..., json_schema_extra=picker("company_id"))
    firstname: str
    lastname: str
    email: str | None = Field(None, description="Stores contact data; does not call a sending endpoint")


class UpdateContact(Contact, Write):
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"x-display-name": "Update Company Contact"})
    firstname: str | None = None
    lastname: str | None = None
    email: str | None = None


class DeleteContact(Contact, Write):
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"x-display-name": "Delete Company Contact"})


class ListOpportunities(Page):
    operation: Literal["list_opportunities"] = Field("list_opportunities", json_schema_extra={"x-display-name": "List Opportunities"})
    company_id: int | None = Field(None, json_schema_extra=picker("company_id"))
    status: Literal["ongoing", "archived", "all"] | None = None


class Opportunity(Config):
    operation: Literal["get_opportunity"] = Field("get_opportunity", json_schema_extra={"x-display-name": "Get Opportunity"})
    company_id: int = Field(..., json_schema_extra=picker("company_id"))
    opportunity_id: int = Field(..., json_schema_extra=picker("opportunity_id", "company_id"))


class CreateOpportunity(Write):
    operation: Literal["create_opportunity"] = Field("create_opportunity", json_schema_extra={"x-display-name": "Create Opportunity"})
    company_id: int = Field(..., json_schema_extra=picker("company_id"))
    name: str
    pipe_name: str | None = None
    pipe_step_name: str | None = None
    due_date_ts: int | None = Field(None, ge=0, strict=True)


class UpdateOpportunity(Opportunity, Write):
    operation: Literal["update_opportunity"] = Field("update_opportunity", json_schema_extra={"x-display-name": "Update Opportunity"})
    name: str | None = None
    pipe_step_name: str | None = None
    due_date_ts: int | None = Field(None, ge=0, strict=True)


class DeleteOpportunity(Opportunity, Write):
    operation: Literal["delete_opportunity"] = Field("delete_opportunity", json_schema_extra={"x-display-name": "Delete Opportunity"})


class ListTasks(Page):
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"x-display-name": "List Tasks"})


class Task(Config):
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"x-display-name": "Get Task"})
    company_id: int = Field(..., json_schema_extra=picker("company_id"))
    task_id: int = Field(..., json_schema_extra=picker("task_id", "company_id"))


class CreateTask(Write):
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"x-display-name": "Create Task"})
    company_id: int = Field(..., json_schema_extra=picker("company_id"))
    project_id: int | None = Field(None, json_schema_extra=picker("project_id", "company_id"))
    title: str
    task_nature_id: int | None = Field(None, json_schema_extra=picker("task_nature_id"))


class UpdateTask(Task, Write):
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"x-display-name": "Update Task"})
    title: str | None = None
    priority: Literal["basse", "normale", "haute", "urgente"] | None = None
    project_id: int | None = Field(None, json_schema_extra=picker("project_id", "company_id"))
    task_status_id: int | None = Field(None, json_schema_extra=picker("task_status_id"))


class DeleteTask(Task, Write):
    operation: Literal["delete_task"] = Field("delete_task", json_schema_extra={"x-display-name": "Delete Task"})


class ListProjects(Page):
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"x-display-name": "List Projects"})
    name: str | None = None
    number: str | None = None


class Project(Config):
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"x-display-name": "Get Project"})
    company_id: int = Field(..., json_schema_extra=picker("company_id"))
    project_id: int = Field(..., json_schema_extra=picker("project_id", "company_id"))


class CreateProject(Write):
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"x-display-name": "Create Project"})
    company_id: int = Field(..., json_schema_extra=picker("company_id"))
    name: str
    number: str | None = None
    parent_project_id: int | None = Field(None, json_schema_extra=picker("parent_project_id", "company_id"))
    project_nature_id: int | None = Field(None, json_schema_extra=picker("project_nature_id"))


class UpdateProject(Project, Write):
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"x-display-name": "Update Project"})
    name: str | None = None
    number: str | None = None
    project_nature_id: int | None = Field(None, json_schema_extra=picker("project_nature_id"))


class DeleteProject(Project, Write):
    operation: Literal["delete_project"] = Field("delete_project", json_schema_extra={"x-display-name": "Delete Project"})


class ListPipes(Page):
    operation: Literal["list_pipes"] = Field("list_pipes", json_schema_extra={"x-display-name": "List Opportunity Pipelines"})


class ListTaskNatures(Page):
    operation: Literal["list_task_natures"] = Field("list_task_natures", json_schema_extra={"x-display-name": "List Task Types"})


class ListTaskStatuses(Config):
    operation: Literal["list_task_statuses"] = Field("list_task_statuses", json_schema_extra={"x-display-name": "List Task Statuses"})


class ListProjectNatures(Config):
    operation: Literal["list_project_natures"] = Field("list_project_natures", json_schema_extra={"x-display-name": "List Project Types"})


Operation = Annotated[Union[Account, ListCompanies, Company, CreateCompany, UpdateCompany, DeleteCompany,
    ListContacts, Contact, CreateContact, UpdateContact, DeleteContact, ListOpportunities, Opportunity,
    CreateOpportunity, UpdateOpportunity, DeleteOpportunity, ListTasks, Task, CreateTask, UpdateTask, DeleteTask,
    ListProjects, Project, CreateProject, UpdateProject, DeleteProject, ListPipes, ListTaskNatures,
    ListTaskStatuses, ListProjectNatures], Field(discriminator="operation")]


class AxonautNodeConfig(NodeConfig[Operation, AxonautAPIKeyCredential]):
    pass


class CurrentCredential(dict):
    def __init__(self, data, authority=None):
        super().__init__(data)
        self.authority = authority


async def freshen(data, **kwargs):
    if kwargs.get("credential_id"):
        if not kwargs.get("user_id"):
            raise AxonautError("Current credential access requires an authenticated actor")
        context = {key: kwargs[key] for key in ("organization_id", "workflow_id") if key in kwargs}
        async def load():
            current = await resolve_credential_with_owner_fallback(
                kwargs["credential_id"], kwargs["user_id"], kwargs.get("pool"),
                org_id=context.get("organization_id"), workflow_id=context.get("workflow_id"))
            if not current:
                raise AxonautError("Current Axonaut credential is unavailable")
            return credential(current)
        return CurrentCredential(await load(), load)
    return CurrentCredential(credential(data))


async def request(data, method, route, *, query=None, body=None, page=None, status=200, no_body=False):
    authority = getattr(data, "authority", None)
    if authority:
        current = await authority()
        if any(current.get(k) != data.get(k) for k in ("credential_type", "api_key")):
            raise AxonautError("Current Axonaut connection changed; retry with the current connection")
    guard(data, stored=True)
    headers = {"userApiKey": data["api_key"], "Accept": "application/json"}
    if page is not None:
        headers["page"] = str(page)
    try:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=30) as client:
            response = await client.request(method, ORIGIN + PREFIX + route, headers=headers, params=query, json=body)
    except httpx.RequestError:
        raise AxonautError("Axonaut could not be reached; this request is unverified") from None
    if response.status_code != status:
        descriptions = {400: "request was invalid", 401: "API key was refused", 403: "permission was denied", 404: "resource was not found", 429: "request limit was reached"}
        delay = response.headers.get("Retry-After")
        retry_after = int(delay) if delay and delay.isascii() and delay.isdecimal() and len(delay) <= 8 else None
        raise AxonautError(f"Axonaut HTTP {response.status_code}: {descriptions.get(response.status_code, 'response was not accepted')}", response.status_code, retry_after)
    if no_body:
        return None  # DELETE has no response schema; never infer a JSON success marker.
    if len(response.content) > MAX_BYTES:
        raise AxonautError("Axonaut response exceeds the supported size")
    try:
        value = response.json()
    except ValueError:
        raise AxonautError("Axonaut returned unreadable JSON") from None
    if not isinstance(value, (dict, list)) or (isinstance(value, dict) and any(k in value for k in ("error", "errors"))):
        raise AxonautError("Axonaut returned an unreadable response")
    return value


def safe_text(value, data, allow_empty=True):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value) or data["api_key"] in value or (not allow_empty and not value):
        raise AxonautError("Axonaut metadata contains unreadable or protected data")
    return value


def projection(row, kind, data):
    if not isinstance(row, dict):
        raise AxonautError("Axonaut returned unreadable resource metadata")
    result = {"id": resource_id(row.get("id"))}
    strings = {"company": ("name", "internal_id", "creation_date"), "contact": ("firstname", "lastname", "job"),
        "opportunity": ("name", "creation_date", "due_date", "end_date", "pipe_name", "pipe_step_name"),
        "task": ("title", "number", "priority", "type"), "project": ("name", "number", "estimated_start", "actual_start", "estimated_end", "actual_end"),
        "catalog": ("name",)}[kind]
    for key in strings:
        if row.get(key) is not None:
            result[key] = safe_text(row[key], data)
    label = "title" if kind == "task" else "name"
    if kind != "contact" and not isinstance(result.get(label), str):
        raise AxonautError("Axonaut returned unreadable resource labels")
    if kind in {"contact", "task", "project"}:
        if type(row.get("company_id")) is not int or row["company_id"] < 0:
            raise AxonautError("Axonaut returned unreadable company binding")
        result["company_id"] = row["company_id"]
    if kind == "opportunity":
        company = row.get("company")
        if not isinstance(company, dict):
            raise AxonautError("Axonaut returned unreadable opportunity company")
        result["company_id"] = resource_id(company.get("id"))
    if kind == "task":
        for key in ("project_id", "task_status_id"):
            if row.get(key) is not None:
                if type(row[key]) is not int or row[key] < 0:
                    raise AxonautError("Axonaut returned unreadable task binding")
                result[key] = row[key]
    if kind == "project" and row.get("parent_project") is not None:
        if not isinstance(row["parent_project"], dict):
            raise AxonautError("Axonaut returned unreadable parent project binding")
        result["parent_project_id"] = resource_id(row["parent_project"].get("id"))
    booleans = {"company": ("is_customer", "is_prospect", "isB2C", "is_disabled"), "opportunity": ("is_win", "is_archived"),
        "catalog": ("is_start_status", "is_close_status", "disabled", "isDisabled", "is_deleted")}.get(kind, ())
    for key in booleans:
        if key in row:
            if type(row[key]) is not bool:
                raise AxonautError("Axonaut returned unreadable record flags")
            result[key] = row[key]
    if kind == "catalog" and "pipe_steps" in row:
        if not isinstance(row["pipe_steps"], list) or len(row["pipe_steps"]) > 1000:
            raise AxonautError("Axonaut returned unreadable pipeline steps")
        result["pipe_steps"] = []
        for step in row["pipe_steps"]:
            if not isinstance(step, dict) or type(step.get("order_number")) is not int:
                raise AxonautError("Axonaut returned unreadable pipeline step")
            result["pipe_steps"].append({"name": safe_text(step.get("name"), data), "order_number": step["order_number"]})
    return result


def account_result(payload, data):
    if not isinstance(payload, dict) or not isinstance(payload.get("account"), list) or len(payload["account"]) > 100:
        raise AxonautError("Axonaut returned unreadable current account metadata")
    result = {"id": resource_id(payload.get("id")), "fullname": safe_text(payload.get("fullname"), data), "accounts": []}
    for row in payload["account"]:
        if not isinstance(row, dict):
            raise AxonautError("Axonaut returned unreadable account metadata")
        account = {"id": resource_id(row.get("id")), "company_name": safe_text(row.get("company_name"), data)}
        for key in ("currency", "account_status"):
            if row.get(key) is not None:
                account[key] = safe_text(row[key], data)
        result["accounts"].append(account)
    if len({row["id"] for row in result["accounts"]}) != len(result["accounts"]):
        raise AxonautError("Axonaut returned duplicate account identifiers")
    return result


async def collection(data, route, kind, *, query=None, page=None):
    payload = await request(data, "GET", route, query=query, page=page)
    if not isinstance(payload, list) or len(payload) > 1000:
        raise AxonautError("Axonaut returned unreadable resource page")
    rows = [projection(row, kind, data) for row in payload]
    if len({row["id"] for row in rows}) != len(rows):
        raise AxonautError("Axonaut returned duplicate resource identifiers")
    return {"items": rows, "requested_page": page, "has_more": None, "next_page_token": None}


async def get_bound(data, kind, resource, identifier, company_id=None):
    row = projection(await request(data, "GET", resource + "/" + str(identifier)), kind, data)
    if row["id"] != identifier or (company_id is not None and row.get("company_id") != company_id):
        raise AxonautError("Axonaut returned a different resource or company binding")
    return row


class AxonautNode(WorkflowNode):
    integration_type = "automation-axonaut"
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_companies", noun="companies", label_keys=("name",),
        identity_operation="get_account", identity_keys=("fullname",), proves="account")
    edit_examples = ["List my companies", "Update a company contact", "Create a task for a project", "Read opportunity metadata"]

    @classmethod
    def get_config_model(cls):
        return AxonautNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data
        try:
            if isinstance(raw, dict) and raw.get("credentials") is not None:
                guard(raw["credentials"])
        except ValueError:
            raise ConfigValidationError("Select a native Axonaut API key") from None
        return super().parse_config(raw)

    @classmethod
    def validate_config(cls, config_data):
        raw = config_data
        try:
            if isinstance(raw, dict) and raw.get("credentials") is not None:
                guard(raw["credentials"])
        except ValueError:
            return {"valid": False, "errors": ["Select a native Axonaut API key"], "satisfied_set": None}
        return super().validate_config(raw)

    @classmethod
    def _extract_actionable_validation_error(cls, error, config_data):
        return "Check the native Axonaut credential and operation fields"

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await freshen(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def validate_credential(cls, data, *, validation_context=None):
        if validation_context is not None:
            result = await validation_context.run_operation("get_account")
            await validation_context.accept(result)
            return {"valid": True, "name": result["data"]["fullname"]}
        try:
            data = await freshen(data)
            row = account_result(await request(data, "GET", "me"), data)
            return {"valid": True, "name": row["fullname"]}
        except AxonautError as exc:
            return {"valid": False if exc.status_code in {401, 403} else None, "error": str(exc)}
        except (ValueError, TypeError, KeyError):
            return {"valid": False, "error": "Check the native Axonaut API key"}

    @classmethod
    async def validate_credential_access(cls, data, *, validation_context=None):
        return await cls.validate_credential(data, validation_context=validation_context)

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if page_token:
            raise ValueError("Axonaut does not document a continuation token; use an explicit list page")
        data = credential_data if isinstance(credential_data, CurrentCredential) else await freshen(credential_data)
        context = context or {}
        parents = {"contact_id", "opportunity_id", "task_id", "project_id", "parent_project_id"}
        company_id = resource_id(context.get("company_id")) if field_name in parents else None
        routes = {"company_id": ("companies", "company"), "contact_id": (f"companies/{company_id}/employees", "contact"),
            "opportunity_id": (f"companies/{company_id}/opportunities", "opportunity"), "task_id": ("tasks", "task"),
            "project_id": ("projects", "project"), "parent_project_id": ("projects", "project"),
            "task_nature_id": ("taskNatures", "catalog"), "task_status_id": ("taskStatus", "catalog"),
            "project_nature_id": ("projectNatures", "catalog")}
        if field_name not in routes:
            raise ValueError("Unknown native Axonaut resource picker")
        route, kind = routes[field_name]
        query = {"search": text(search), "type": "all"} if field_name == "company_id" and search else None
        rows = (await collection(data, route, kind, query=query))["items"]
        if company_id is not None:
            if field_name in {"contact_id", "opportunity_id"} and any(row["company_id"] != company_id for row in rows):
                raise AxonautError("Axonaut returned a different company resource")
            rows = [row for row in rows if row.get("company_id") == company_id]
        options = []
        for row in rows:
            label = row.get("name") or row.get("title") or " ".join(row.get(k, "") for k in ("firstname", "lastname")).strip() or str(row["id"])
            if not search or field_name == "company_id" or search.casefold() in label.casefold():
                options.append({"value": str(row["id"]), "label": label})
        return {"options": options, "next_page_token": None}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a native Axonaut API key")
        config = self.config.config
        try:
            nested = self.node_data.get("config") or {}
            cid = self.node_data.get("credential_id")
            if isinstance(nested, dict) and nested.get("credential_id"):
                if cid and cid != nested["credential_id"]:
                    raise AxonautError("Axonaut credential selection is ambiguous")
                cid = nested["credential_id"]
            data = await freshen(self.config.credentials.model_dump(mode="json"), credential_id=cid,
                pool=self.node_data.get("_approval_pool"), user_id=self.user_id,
                organization_id=self.organization_id, workflow_id=self.workflow_id)
            return {"status": "success", "action": config.operation, "data": await self._operation(data, config)}
        except AxonautError as exc:
            return {"status": "error", "action": config.operation, "error": str(exc), "status_code": exc.status_code, "retry_after": exc.retry_after}
        except (ValueError, TypeError, KeyError):
            return {"status": "error", "action": config.operation, "error": "Axonaut credential or response could not be validated"}

    async def _operation(self, data, config):
        op = config.operation
        if op == "get_account":
            return account_result(await request(data, "GET", "me"), data)
        lists = {"list_companies": ("companies", "company"), "list_contacts": ("employees", "contact"),
            "list_opportunities": ("opportunities", "opportunity"), "list_tasks": ("tasks", "task"),
            "list_projects": ("projects", "project"), "list_pipes": ("pipes", "catalog"),
            "list_task_natures": ("taskNatures", "catalog"), "list_task_statuses": ("taskStatus", "catalog"),
            "list_project_natures": ("projectNatures", "catalog")}
        if op in lists:
            route, kind = lists[op]
            query = {}
            if op == "list_companies":
                query["type"] = config.company_type
                for key in ("search", "internal_id"):
                    if getattr(config, key):
                        query[key] = getattr(config, key)
            elif op in {"list_contacts", "list_opportunities"}:
                if config.company_id:
                    route = f"companies/{config.company_id}/" + ("employees" if kind == "contact" else "opportunities")
                    await get_bound(data, "company", "companies", config.company_id)
                if op == "list_contacts":
                    # Names are documented query filters only on /employees.
                    if config.company_id and (config.firstname or config.lastname):
                        raise AxonautError("Use an account-wide contact list for name query filters")
                    query = {k: getattr(config, k) for k in ("firstname", "lastname") if getattr(config, k)}
                elif config.status:
                    query["status"] = config.status
            elif op == "list_projects":
                query = {k: getattr(config, k) for k in ("name", "number") if getattr(config, k)}
            result = await collection(data, route, kind, query=query, page=getattr(config, "page", None))
            if op in {"list_contacts", "list_opportunities"} and config.company_id and any(row["company_id"] != config.company_id for row in result["items"]):
                raise AxonautError("Axonaut returned a different company resource")
            return result
        action, kind = op.split("_", 1)
        resources = {"company": "companies", "contact": "employees", "opportunity": "opportunities", "task": "tasks", "project": "projects"}
        resource = resources[kind]
        company_id = getattr(config, "company_id", None) if kind != "company" else None
        identifier = getattr(config, kind + "_id", None) if action != "create" else None
        if action != "create":
            current = await get_bound(data, kind, resource, identifier, company_id)
            if action == "get":
                return current
        if action == "delete":
            await request(data, "DELETE", resource + "/" + str(identifier), status=202 if kind == "company" else 200, no_body=True)
            return {"id": identifier, "deletion_request_acknowledged": True, "pending": True if kind == "company" else None, "deletion_verified": None}
        if company_id is not None:
            await get_bound(data, "company", "companies", company_id)
        if getattr(config, "project_id", None) and kind == "task":
            await get_bound(data, "project", "projects", config.project_id, company_id)
        if getattr(config, "parent_project_id", None):
            await get_bound(data, "project", "projects", config.parent_project_id, company_id)
        fields = {"company": ("name", "internal_id"), "contact": ("firstname", "lastname", "email"),
            "opportunity": ("name", "pipe_step_name", "due_date_ts"), "task": ("title", "project_id"),
            "project": ("name", "number", "project_nature_id")}[kind]
        body = {key: getattr(config, key) for key in fields if getattr(config, key, None) is not None}
        if action == "create":
            if kind == "company":
                body.update(isB2C=False, is_prospect=config.is_prospect, is_customer=config.is_customer)
            else:
                body["company_id"] = company_id
            if kind == "opportunity" and config.pipe_name:
                body["pipe_name"] = config.pipe_name
            if kind == "task" and config.task_nature_id:
                body["task_nature_id"] = config.task_nature_id
            if kind == "project" and config.parent_project_id:
                body["parent_project_id"] = config.parent_project_id
        else:
            if kind == "task":
                for key in ("priority", "task_status_id"):
                    if getattr(config, key) is not None:
                        body[key] = getattr(config, key)
            if not body:
                raise AxonautError("Choose at least one documented field to update")
        result = projection(await request(data, "POST" if action == "create" else "PATCH",
            resource if action == "create" else resource + "/" + str(identifier), body=body), kind, data)
        if (identifier is not None and result["id"] != identifier) or (company_id is not None and result.get("company_id") != company_id):
            raise AxonautError("Axonaut returned a different changed resource")
        if kind == "task" and config.project_id is not None and result.get("project_id") != config.project_id:
            raise AxonautError("Axonaut returned a different task project binding")
        if getattr(config, "parent_project_id", None) is not None and result.get("parent_project_id") != config.parent_project_id:
            raise AxonautError("Axonaut returned a different parent project binding")
        return {"resource": result, "write_acknowledged": True, "verified_readback": None}
