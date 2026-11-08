"""MOCO project, CRM and time-tracking operations using a pasted API key.

Each operation sends one request to the published v1 API. Collection reads expose
one page at a time so workflows control pagination without hidden extra requests.
"""
from __future__ import annotations

import json
import re
from datetime import date as Date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class MocoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="MOCO API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.mocoapp.com/",
        "x-credential-instructions": "In MOCO, open your profile's Integrations tab and copy the API key. Enter the account subdomain from your MOCO URL, such as mycompany from https://mycompany.mocoapp.com. An account API key from Settings > Extensions > API & Webhooks also works; writes require full access. Requests use the key's permissions and user identity."})
    credential_type: Literal["moco_api_key"] = Field("moco_api_key", json_schema_extra={"ui:hidden": True})
    subdomain: str = Field(..., title="Account subdomain", description="Only the account name before .mocoapp.com, without https:// or a path.")
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("subdomain", mode="before")
    @classmethod
    def account(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter the account subdomain")
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Use only the account subdomain before .mocoapp.com")
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without an Authorization prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number, starting at 1.")
    per_page: int = Field(100, ge=1, le=100, title="Page size")
    updated_after: datetime | None = Field(None, description="Only records updated after this ISO8601 timestamp.")


class _CompanyFields(_Input):
    type: Literal["customer", "supplier", "organization"] | None = None
    name: str | None = Field(None, min_length=1)
    identifier: str | None = None
    email: str | None = None
    address: str | None = None
    country_code: str | None = None
    currency: str | None = None
    phone: str | None = None
    website: str | None = None
    info: str | None = None
    customer_vat_code_id: int | None = Field(None, ge=1)
    default_invoice_due_days: int | None = Field(None, ge=0)


class _ContactFields(_Input):
    firstname: str | None = None
    lastname: str | None = None
    work_email: str | None = None
    work_phone: str | None = None
    mobile_phone: str | None = None
    job_position: str | None = None
    company_id: int | None = Field(None, ge=1)
    info: str | None = None


class _ProjectFields(_Input):
    name: str | None = Field(None, min_length=1)
    identifier: str | None = None
    company_id: int | None = Field(None, ge=1)
    leader_id: int | None = Field(None, ge=1)
    currency: str | None = None
    start_date: Date | None = None
    finish_date: Date | None = None
    fixed_price: bool | None = None
    budget: float | None = Field(None, ge=0, allow_inf_nan=False)
    hourly_rate: float | None = Field(None, ge=0, allow_inf_nan=False)
    billing_variant: Literal["project", "task", "user"] | None = None
    info: str | None = None


class _ActivityFields(_Input):
    date: Date | None = None
    project_id: int | None = Field(None, ge=1)
    task_id: int | None = Field(None, ge=1)
    seconds: int | None = Field(None, ge=0)
    description: str | None = None
    billable: bool | None = None
    tag: str | None = None
    remote_id: str | None = None
    remote_url: str | None = None
    remote_service: Literal["", "trello", "jira", "asana", "basecamp", "wunderlist", "basecamp2", "basecamp3", "toggl", "mite", "github", "youtrack"] | None = None


class _DealFields(_Input):
    name: str | None = Field(None, min_length=1)
    deal_category_id: int | None = Field(None, ge=1)
    company_id: int | None = Field(None, ge=1)
    person_id: int | None = Field(None, ge=1)
    user_id: int | None = Field(None, ge=1)
    money: float | None = Field(None, allow_inf_nan=False)
    currency: str | None = None
    status: Literal["potential", "pending", "won", "lost", "dropped"] | None = None
    reminder_date: Date | None = None
    closed_on: Date | None = None
    info: str | None = None


class ListCompanys(_Page):
    operation: Literal["list_companies"] = Field("list_companies", title="List companies", json_schema_extra={"ui:hidden": True})
    type: Literal["customer", "supplier", "organization"] | None = None
    term: str | None = None
    tags: str | None = Field(None, description="Comma-separated tags.")
    include_archived: bool | None = None


class GetCompany(_Input):
    operation: Literal["get_company"] = Field("get_company", title="Get company", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., ge=1, description="MOCO company ID.")


class CreateCompany(_CompanyFields):
    operation: Literal["create_company"] = Field("create_company", title="Create company", json_schema_extra={"ui:hidden": True})
    type: Literal["customer", "supplier", "organization"] = "customer"
    name: str = Field(..., min_length=1)
    tags_json: str | None = Field(None, description='JSON array of tags, for example ["VIP"]. Omit to preserve existing tags.', json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})
    custom_properties_json: str | None = Field(None, description="JSON object keyed by preconfigured MOCO custom-field names. Unknown fields are ignored by MOCO.", json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})


class UpdateCompany(_CompanyFields):
    operation: Literal["update_company"] = Field("update_company", title="Update company", json_schema_extra={"ui:hidden": True})
    company_id: int = Field(..., ge=1, description="MOCO company ID.")
    tags_json: str | None = Field(None, description='JSON array of tags, for example ["VIP"]. Omit to preserve existing tags.', json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})
    custom_properties_json: str | None = Field(None, description="JSON object keyed by preconfigured MOCO custom-field names. Unknown fields are ignored by MOCO.", json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})


class ListContacts(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List contacts", json_schema_extra={"ui:hidden": True})
    term: str | None = None
    tags: str | None = None


class GetContact(_Input):
    operation: Literal["get_contact"] = Field("get_contact", title="Get contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., ge=1, description="MOCO contact ID.")


class CreateContact(_ContactFields):
    operation: Literal["create_contact"] = Field("create_contact", title="Create contact", json_schema_extra={"ui:hidden": True})
    firstname: str = Field(..., min_length=1)
    lastname: str = Field(..., min_length=1)
    tags_json: str | None = Field(None, description='JSON array of tags, for example ["VIP"]. Omit to preserve existing tags.', json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})
    custom_properties_json: str | None = Field(None, description="JSON object keyed by preconfigured MOCO custom-field names. Unknown fields are ignored by MOCO.", json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})


class UpdateContact(_ContactFields):
    operation: Literal["update_contact"] = Field("update_contact", title="Update contact", json_schema_extra={"ui:hidden": True})
    contact_id: int = Field(..., ge=1, description="MOCO contact ID.")
    tags_json: str | None = Field(None, description='JSON array of tags, for example ["VIP"]. Omit to preserve existing tags.', json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})
    custom_properties_json: str | None = Field(None, description="JSON object keyed by preconfigured MOCO custom-field names. Unknown fields are ignored by MOCO.", json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})


class ListProjects(_Page):
    operation: Literal["list_projects"] = Field("list_projects", title="List projects", json_schema_extra={"ui:hidden": True})
    company_id: str | None = Field(None, description="Company ID filter.")
    term: str | None = None
    include_archived: bool | None = None


class GetProject(_Input):
    operation: Literal["get_project"] = Field("get_project", title="Get project", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., ge=1, description="MOCO project ID.")


class CreateProject(_ProjectFields):
    operation: Literal["create_project"] = Field("create_project", title="Create project", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    company_id: int = Field(..., ge=1)
    leader_id: int = Field(..., ge=1)
    currency: str = Field(..., min_length=3, max_length=3)
    tags_json: str | None = Field(None, description='JSON array of tags, for example ["VIP"]. Omit to preserve existing tags.', json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})
    custom_properties_json: str | None = Field(None, description="JSON object keyed by preconfigured MOCO custom-field names. Unknown fields are ignored by MOCO.", json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})


class UpdateProject(_ProjectFields):
    operation: Literal["update_project"] = Field("update_project", title="Update project", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., ge=1, description="MOCO project ID.")
    tags_json: str | None = Field(None, description='JSON array of tags, for example ["VIP"]. Omit to preserve existing tags.', json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})
    custom_properties_json: str | None = Field(None, description="JSON object keyed by preconfigured MOCO custom-field names. Unknown fields are ignored by MOCO.", json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})


class ListActivitys(_Page):
    operation: Literal["list_activities"] = Field("list_activities", title="List activities", json_schema_extra={"ui:hidden": True})
    from_date: Date | None = Field(None, title="From date")
    to_date: Date | None = Field(None, title="To date")
    project_id: int | None = Field(None, ge=1)
    user_id: int | None = Field(None, ge=1)
    billable: bool | None = None
    billed: bool | None = None


class GetActivity(_Input):
    operation: Literal["get_activity"] = Field("get_activity", title="Get activity", json_schema_extra={"ui:hidden": True})
    activity_id: int = Field(..., ge=1, description="MOCO activity ID.")


class CreateActivity(_ActivityFields):
    operation: Literal["create_activity"] = Field("create_activity", title="Create activity", json_schema_extra={"ui:hidden": True})
    date: Date
    project_id: int = Field(..., ge=1)
    task_id: int = Field(..., ge=1)
    seconds: int = Field(..., ge=0)


class UpdateActivity(_ActivityFields):
    operation: Literal["update_activity"] = Field("update_activity", title="Update activity", json_schema_extra={"ui:hidden": True})
    activity_id: int = Field(..., ge=1, description="MOCO activity ID.")


class DeleteActivity(_Input):
    operation: Literal["delete_activity"] = Field("delete_activity", title="Delete activity", json_schema_extra={"ui:hidden": True})
    activity_id: int = Field(..., ge=1, description="MOCO activity ID.")


class ListDeals(_Page):
    operation: Literal["list_deals"] = Field("list_deals", title="List deals", json_schema_extra={"ui:hidden": True})
    status: Literal["potential", "pending", "won", "lost", "dropped"] | None = None
    company_id: int | None = Field(None, ge=1)


class GetDeal(_Input):
    operation: Literal["get_deal"] = Field("get_deal", title="Get deal", json_schema_extra={"ui:hidden": True})
    deal_id: int = Field(..., ge=1, description="MOCO deal ID.")


class CreateDeal(_DealFields):
    operation: Literal["create_deal"] = Field("create_deal", title="Create deal", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    deal_category_id: int = Field(..., ge=1)
    money: float = Field(..., allow_inf_nan=False)
    currency: str = Field(..., min_length=3, max_length=3)
    tags_json: str | None = Field(None, description='JSON array of tags, for example ["VIP"]. Omit to preserve existing tags.', json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})
    custom_properties_json: str | None = Field(None, description="JSON object keyed by preconfigured MOCO custom-field names. Unknown fields are ignored by MOCO.", json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})


class UpdateDeal(_DealFields):
    operation: Literal["update_deal"] = Field("update_deal", title="Update deal", json_schema_extra={"ui:hidden": True})
    deal_id: int = Field(..., ge=1, description="MOCO deal ID.")
    tags_json: str | None = Field(None, description='JSON array of tags, for example ["VIP"]. Omit to preserve existing tags.', json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})
    custom_properties_json: str | None = Field(None, description="JSON object keyed by preconfigured MOCO custom-field names. Unknown fields are ignored by MOCO.", json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"})


class ListInvoices(_Page):
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True})
    status: str | None = None
    company_id: str | None = None
    project_id: str | None = None
    date_from: Date | None = None
    date_to: Date | None = None


class GetInvoice(_Input):
    operation: Literal["get_invoice"] = Field("get_invoice", json_schema_extra={"ui:hidden": True})
    invoice_id: int = Field(..., ge=1)


class ListUsers(_Page):
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    include_archived: bool | None = None
    email: str | None = None


class ListProjectTasks(_Page):
    operation: Literal["list_project_tasks"] = Field("list_project_tasks", json_schema_extra={"ui:hidden": True})
    project_id: int = Field(..., ge=1)


Operation = Annotated[Union[ListCompanys, GetCompany, CreateCompany, UpdateCompany, ListContacts, GetContact, CreateContact, UpdateContact, ListProjects, GetProject, CreateProject, UpdateProject, ListActivitys, GetActivity, CreateActivity, UpdateActivity, DeleteActivity, ListDeals, GetDeal, CreateDeal, UpdateDeal, ListInvoices, GetInvoice, ListUsers, ListProjectTasks], Field(discriminator="operation")]


class MocoConfig(NodeConfig[Operation, MocoAPIKeyCredential]):
    pass


ROUTES = {'list_companies': ('GET', '/companies'), 'get_company': ('GET', '/companies/{company_id}'), 'create_company': ('POST', '/companies'), 'update_company': ('PUT', '/companies/{company_id}'), 'list_contacts': ('GET', '/contacts/people'), 'get_contact': ('GET', '/contacts/people/{contact_id}'), 'create_contact': ('POST', '/contacts/people'), 'update_contact': ('PUT', '/contacts/people/{contact_id}'), 'list_projects': ('GET', '/projects'), 'get_project': ('GET', '/projects/{project_id}'), 'create_project': ('POST', '/projects'), 'update_project': ('PUT', '/projects/{project_id}'), 'list_activities': ('GET', '/activities'), 'get_activity': ('GET', '/activities/{activity_id}'), 'create_activity': ('POST', '/activities'), 'update_activity': ('PUT', '/activities/{activity_id}'), 'delete_activity': ('DELETE', '/activities/{activity_id}'), 'list_deals': ('GET', '/deals'), 'get_deal': ('GET', '/deals/{deal_id}'), 'create_deal': ('POST', '/deals'), 'update_deal': ('PUT', '/deals/{deal_id}'), 'list_invoices': ('GET', '/invoices'), 'get_invoice': ('GET', '/invoices/{invoice_id}'), 'list_users': ('GET', '/users'), 'list_project_tasks': ('GET', '/projects/{project_id}/tasks')}


class MocoNode(WorkflowNode):
    integration_type = "automation-moco"
    connection_evidence = ConnectionEvidence(operation="list_companies", noun="companies", label_keys=("name", "identifier", "id"))
    edit_examples = ["Create a customer in MOCO", "Log time on a project", "List unpaid invoices", "Update a sales deal"]

    @classmethod
    def get_config_model(cls):
        return MocoConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a MOCO API key")
        config, credential = self.config.config, self.config.credentials
        method, template = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in re.findall(r"\{(\w+)\}", template):
            template = template.replace("{" + field + "}", str(values.pop(field)))
        origin = "https://" + credential.subdomain + ".mocoapp.com"
        url = origin + "/api/v1" + template
        payload = None
        params = None
        if config.operation.startswith("list_"):
            params = { {"from_date": "from", "to_date": "to"}.get(k, k):
                      str(v).lower() if isinstance(v, bool) else v for k, v in values.items() }
        elif method in {"POST", "PUT"}:
            payload = values
            for field, target, expected in (("tags_json", "tags", list), ("custom_properties_json", "custom_properties", dict)):
                if field in payload:
                    try:
                        parsed = json.loads(payload.pop(field))
                    except (TypeError, ValueError):
                        raise ValueError(f"{target} must be valid JSON") from None
                    if not isinstance(parsed, expected) or (target == "tags" and any(not isinstance(v, str) for v in parsed)):
                        raise ValueError(f"{target} has the wrong JSON shape")
                    payload[target] = parsed
            if not payload:
                raise ValueError("Supply at least one field to update")
        headers = {"Authorization": "Token token=" + credential.api_key,
                   "Accept": "application/json", "Content-Type": "application/json"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, url, headers=headers, params=params, json=payload)
        if not 200 <= response.status_code < 300:
            try:
                message = json.dumps(response.json(), ensure_ascii=False)
            except ValueError:
                message = response.text
            message = message.replace(credential.api_key, "[redacted]")[:4000]
            result = {"status": "error", "status_code": response.status_code, "error": message}
        elif method == "DELETE":
            result = {"status": "success", "deleted": True}
        else:
            body = response.json()
            if config.operation.startswith("list_"):
                if not isinstance(body, list) or any(not isinstance(row, dict) for row in body):
                    raise ValueError("MOCO returned an unexpected collection")
                next_page = None
                for link in response.headers.get("Link", "").split(","):
                    match = re.match(r'\s*<([^>]+)>;\s*rel="next"', link)
                    if not match:
                        continue
                    target = urlsplit(match.group(1))
                    if target.scheme != "https" or target.netloc != urlsplit(origin).netloc or target.path != urlsplit(url).path:
                        raise ValueError("MOCO returned an invalid pagination link")
                    page_values = parse_qs(target.query).get("page", [])
                    if len(page_values) != 1 or not page_values[0].isdigit() or int(page_values[0]) <= config.page:
                        raise ValueError("MOCO returned an invalid next page")
                    next_page = int(page_values[0])
                result = {"status": "success", "items": body, "page": config.page, "next_page": next_page, "has_more": next_page is not None}
            else:
                if not isinstance(body, dict) or "errors" in body:
                    raise ValueError("MOCO returned an unexpected record")
                result = {"status": "success", "item": body}
        await self.emit(result)
        return result
