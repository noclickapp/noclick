"""Benchmark Email (2026 API) contacts, lists, campaign drafts and reports.

The account-specific API URL is shown alongside API keys in Benchmark Email.
The API currently creates campaign drafts but cannot send or schedule them.
"""

import json
import re
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


_BASE_URL = re.compile(r"https://api-[a-z0-9-]+\.benchmarkemail\.io\Z")
_ID = re.compile(r"[a-fA-F0-9]{24}\Z")


class BenchmarkEmailCredential(BaseModel):
    credential_type: Literal["benchmark_email_api_key"] = Field(
        "benchmark_email_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})
    api_base_url: str = Field(
        ...,
        title="API Base URL",
        description="Copy the regional URL shown next to the key in Benchmark Email's API Keys page.",
    )

    @field_validator("api_base_url")
    @classmethod
    def valid_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/").lower()
        if not _BASE_URL.fullmatch(value):
            raise ValueError("Use the HTTPS api-…benchmarkemail.io URL from API Keys")
        return value

    model_config = ConfigDict(title="Benchmark Email API Key", json_schema_extra={
        "x-credential-url": "https://app.benchmarkemail.io/",
        "x-credential-instructions": (
            "In Benchmark Email, open Integrations → API Keys. Create a key with "
            "contacts:read/write, campaigns:read/write, reports:read and domains:read "
            "as needed. Copy the key and its account-specific API Base URL."
        ),
    })


def _op(name: str, category: str, title: str) -> Any:
    return Field(name, title=title, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category, "x-display-name": title,
    })


def _structure() -> Any:
    return Field(..., title="Contact Structure", json_schema_extra={
        "x-dynamic-options": {"field_name": "contact_structure_id", "searchable": True,
                              "allow_custom": True, "placeholder": "Select a contact structure…"}
    })


def _list() -> Any:
    return Field(..., title="List", json_schema_extra={
        "x-dynamic-options": {"field_name": "list_id", "searchable": True,
                              "allow_custom": True, "placeholder": "Select a list…"}
    })


class ListStructures(BaseModel):
    operation: Literal["list_contact_structures"] = _op("list_contact_structures", "Contact Structures", "List Contact Structures")


class GetStructure(BaseModel):
    operation: Literal["get_contact_structure"] = _op("get_contact_structure", "Contact Structures", "Get Contact Structure")
    contact_structure_id: str = _structure()


class ListLists(BaseModel):
    operation: Literal["list_lists"] = _op("list_lists", "Lists", "List Lists")
    contact_structure_id: str = _structure()
    page: int = Field(1, ge=1, title="Page")
    size: int = Field(25, ge=1, le=100, title="Page Size")
    criteria: Optional[str] = Field(None, title="Search Name")


class GetList(BaseModel):
    operation: Literal["get_list"] = _op("get_list", "Lists", "Get List")
    contact_structure_id: str = _structure()
    list_id: str = _list()


class CreateList(BaseModel):
    operation: Literal["create_list"] = _op("create_list", "Lists", "Create List")
    contact_structure_id: str = _structure()
    name: str = Field(..., min_length=1, max_length=1000, title="Name")


class RenameList(BaseModel):
    operation: Literal["rename_list"] = _op("rename_list", "Lists", "Rename List")
    contact_structure_id: str = _structure()
    list_id: str = _list()
    name: str = Field(..., min_length=1, max_length=1000, title="New Name")


class DuplicateList(BaseModel):
    operation: Literal["duplicate_list"] = _op("duplicate_list", "Lists", "Duplicate List")
    contact_structure_id: str = _structure()
    list_id: str = _list()
    name: str = Field(..., min_length=1, max_length=1000, title="New Name")


class DeleteList(BaseModel):
    operation: Literal["delete_list"] = _op("delete_list", "Lists", "Delete List")
    contact_structure_id: str = _structure()
    list_id: str = _list()


class MergeLists(BaseModel):
    operation: Literal["merge_lists"] = _op("merge_lists", "Lists", "Merge Lists")
    contact_structure_id: str = _structure()
    name: str = Field(..., min_length=1, max_length=1000, title="New List Name")
    list_ids: str = Field(..., title="Source List IDs", description="Comma-separated IDs of lists to merge")


class SearchContacts(BaseModel):
    operation: Literal["search_contacts"] = _op("search_contacts", "Contacts", "Search Contacts by Email")
    contact_structure_id: str = _structure()
    email: str = Field(..., title="Email")
    page: int = Field(1, ge=1, title="Page")
    page_size: int = Field(25, ge=1, le=100, title="Page Size")


class GetContact(BaseModel):
    operation: Literal["get_contact"] = _op("get_contact", "Contacts", "Get Contact")
    contact_id: str = Field(..., title="Contact ID")


class CreateContact(BaseModel):
    operation: Literal["create_contact"] = _op("create_contact", "Contacts", "Create Contact")
    contact_structure_id: str = _structure()
    email: str = Field(..., title="Email")
    fields_json: Optional[str] = Field(None, title="Custom Fields (JSON)", description='Array of {"_id":"field id","value":"..."}', json_schema_extra={"ui:widget": "textarea"})
    list_ids: Optional[str] = Field(None, title="List IDs", description="Comma-separated list IDs")


class UpdateContact(BaseModel):
    operation: Literal["update_contact"] = _op("update_contact", "Contacts", "Update Contact")
    contact_id: str = Field(..., title="Contact ID")
    email: Optional[str] = Field(None, title="New Email")
    fields_json: Optional[str] = Field(None, title="Replacement Custom Fields (JSON)", description="Array of field ID/value objects. Omit to preserve current fields.", json_schema_extra={"ui:widget": "textarea"})
    list_ids: Optional[str] = Field(None, title="Replacement List IDs", description="Comma-separated IDs. Omit to preserve current lists; empty removes all.")


class UnsubscribeContact(BaseModel):
    operation: Literal["unsubscribe_contact"] = _op("unsubscribe_contact", "Contacts", "Unsubscribe Contact")
    contact_id: str = Field(..., title="Contact ID")


class DeleteContact(BaseModel):
    operation: Literal["delete_contact"] = _op("delete_contact", "Contacts", "Delete Contact")
    contact_id: str = Field(..., title="Contact ID")


class ListCampaigns(BaseModel):
    operation: Literal["list_campaigns"] = _op("list_campaigns", "Campaigns", "List Campaigns")
    page: int = Field(1, ge=1, title="Page")
    size: int = Field(25, ge=1, le=100, title="Page Size")
    criteria: Optional[str] = Field(None, title="Search Name")
    statuses: Optional[str] = Field(None, title="Statuses", description="Comma-separated: draft, scheduled, sent, sending, paused, failed, cancelled")


class GetCampaign(BaseModel):
    operation: Literal["get_campaign"] = _op("get_campaign", "Campaigns", "Get Campaign")
    campaign_id: str = Field(..., title="Campaign ID")


class CreateCampaign(BaseModel):
    operation: Literal["create_campaign"] = _op("create_campaign", "Campaigns", "Create Campaign Draft")
    name: str = Field(..., min_length=1, title="Name")
    subject: Optional[str] = Field(None, title="Subject")
    from_email: Optional[str] = Field(None, title="From Email")
    from_name: Optional[str] = Field(None, title="From Name")
    reply_to_addresses: Optional[str] = Field(None, title="Reply-To Addresses", description="Comma-separated email addresses")
    preview_text: Optional[str] = Field(None, title="Preview Text")
    html_body: Optional[str] = Field(None, title="HTML Body", json_schema_extra={"ui:widget": "textarea"})
    plain_text_body: Optional[str] = Field(None, title="Plain Text Body", json_schema_extra={"ui:widget": "textarea"})
    contact_structure_id: Optional[str] = Field(None, title="Contact Structure ID")
    list_ids: Optional[str] = Field(None, title="List IDs", description="Comma-separated IDs")


class UpdateCampaign(BaseModel):
    operation: Literal["update_campaign"] = _op("update_campaign", "Campaigns", "Update Campaign Draft")
    campaign_id: str = Field(..., title="Campaign ID")
    name: Optional[str] = Field(None, title="Name")
    from_email: Optional[str] = Field(None, title="From Email")
    from_name: Optional[str] = Field(None, title="From Name")
    reply_to_addresses: Optional[str] = Field(None, title="Reply-To Addresses", description="Comma-separated email addresses")
    subject: Optional[str] = Field(None, title="Subject")
    preview_text: Optional[str] = Field(None, title="Preview Text")
    html_body: Optional[str] = Field(None, title="HTML Body", json_schema_extra={"ui:widget": "textarea"})
    plain_text_body: Optional[str] = Field(None, title="Plain Text Body", json_schema_extra={"ui:widget": "textarea"})
    contact_structure_id: Optional[str] = Field(None, title="Contact Structure ID")
    list_ids: Optional[str] = Field(None, title="List IDs", description="Comma-separated IDs")


class DuplicateCampaign(BaseModel):
    operation: Literal["duplicate_campaign"] = _op("duplicate_campaign", "Campaigns", "Duplicate Campaign")
    campaign_id: str = Field(..., title="Campaign ID")
    name: str = Field(..., min_length=1, title="New Campaign Name")


class DeleteCampaign(BaseModel):
    operation: Literal["delete_campaign"] = _op("delete_campaign", "Campaigns", "Delete Campaign")
    campaign_id: str = Field(..., title="Campaign ID")


class ListDomains(BaseModel):
    operation: Literal["list_domains"] = _op("list_domains", "Account", "List Sending Domains")


class ListTemplates(BaseModel):
    operation: Literal["list_templates"] = _op("list_templates", "Campaigns", "List Templates")
    language: str = Field(..., min_length=1, title="Language", description="Language code for the templates, for example en.")


class DashboardReport(BaseModel):
    operation: Literal["dashboard_report"] = _op("dashboard_report", "Reports", "Get Dashboard Report")
    past_days: int = Field(30, ge=1, le=90, title="Past Days")
    timezone: Optional[str] = Field(None, title="Timezone", description="IANA timezone, for example America/New_York. Defaults to UTC.")


class EmailOverallReport(BaseModel):
    operation: Literal["email_overall_report"] = _op("email_overall_report", "Reports", "Get Overall Email Report")
    past_days: int = Field(30, ge=1, le=90, title="Past Days")
    timezone: Optional[str] = Field(None, title="Timezone", description="IANA timezone, for example America/New_York. Defaults to UTC.")


class EmailCampaignReport(BaseModel):
    operation: Literal["email_campaign_report"] = _op("email_campaign_report", "Reports", "Get Campaign Email Report")
    campaign_id: str = Field(..., title="Campaign ID")


BenchmarkEmailConfig = Annotated[Union[
    ListStructures, GetStructure, ListLists, GetList, CreateList, RenameList,
    DuplicateList, DeleteList, MergeLists, SearchContacts, GetContact, CreateContact,
    UpdateContact, UnsubscribeContact, DeleteContact, ListCampaigns, GetCampaign,
    CreateCampaign, UpdateCampaign, DuplicateCampaign, DeleteCampaign, ListDomains,
    ListTemplates, DashboardReport, EmailOverallReport, EmailCampaignReport,
], Discriminator("operation")]


class BenchmarkEmailNodeConfig(NodeConfig[BenchmarkEmailConfig, BenchmarkEmailCredential]):
    pass


def _resource_id(value: str) -> str:
    if not _ID.fullmatch(value):
        raise ValueError("Benchmark Email resource IDs must be 24 hexadecimal characters")
    return value


def _csv_ids(raw: Optional[str]) -> list[dict[str, str]]:
    return [{"_id": _resource_id(value.strip())} for value in (raw or "").split(",") if value.strip()]


def _id_list(raw: Optional[str]) -> list[str]:
    return [_resource_id(value.strip()) for value in (raw or "").split(",") if value.strip()]


def _fields(raw: Optional[str]) -> list[dict[str, Any]]:
    data = json.loads(raw or "[]")
    if not isinstance(data, list) or any(
        not isinstance(item, dict) or set(item) != {"_id", "value"} or
        not isinstance(item["value"], (str, int, float, bool)) for item in data
    ):
        raise ValueError('Custom fields must be an array of {"_id": "field ID", "value": "..."}')
    return [{"_id": _resource_id(item["_id"]), "value": item["value"]} for item in data]


def _body_campaign(op: Any) -> dict[str, Any]:
    mapping = {
        "name": "name", "subject": "subject", "from_email": "from",
        "from_name": "fromName", "preview_text": "previewText",
        "html_body": "body", "plain_text_body": "plainTextBody",
        "contact_structure_id": "contactStructureId",
    }
    body = {target: getattr(op, source) for source, target in mapping.items()
            if hasattr(op, source) and getattr(op, source) is not None}
    if getattr(op, "list_ids", None) is not None:
        body["lists"] = _id_list(op.list_ids)
    if getattr(op, "reply_to_addresses", None) is not None:
        body["replyToAddresses"] = [value.strip() for value in op.reply_to_addresses.split(",") if value.strip()]
    return body


async def _request(credential: BenchmarkEmailCredential, method: str, path: str,
                   *, body: Optional[dict] = None, params: Optional[dict] = None,
                   action: str) -> dict[str, Any]:
    # Revalidate here because persisted credentials can predate current schema.
    base = BenchmarkEmailCredential.valid_base_url(credential.api_base_url)
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.request(
                method, f"{base}{path}", headers={"X-API-Key": credential.api_key,
                                                   "Accept": "application/json"},
                json=body, params={key: value for key, value in (params or {}).items()
                                   if value is not None and value != ""},
            )
    except httpx.RequestError as exc:
        return {"status": "error", "action": action, "error": type(exc).__name__}
    try:
        data = response.json() if response.content else {"success": True}
    except ValueError:
        data = {"raw": response.text[:1000]}
    timing = {"api_request": round((time.monotonic() - started) * 1000, 2)}
    if response.status_code >= 300:
        detail = data.get("message") or data.get("error") or data.get("name") if isinstance(data, dict) else None
        return {"status": "error", "action": action, "status_code": response.status_code,
                "error": str(detail or f"HTTP {response.status_code}"), "data": data,
                "timing_ms": timing}
    return {"status": "success", "action": action, "status_code": response.status_code,
            "data": data, "timing_ms": timing}


class BenchmarkEmailNode(WorkflowNode):
    """Manage Benchmark Email contacts, lists, campaign drafts, and reports."""

    integration_type = "automation-benchmark-email"

    connection_evidence = ConnectionEvidence(field="contact_structure_id", noun="contact structures")
    edit_examples = [
        "Add a new subscriber to a Benchmark Email list",
        "Find a Benchmark Email contact by email address",
        "Create a campaign draft for a newsletter",
    ]

    @classmethod
    def get_config_model(cls):
        return BenchmarkEmailNodeConfig

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: Dict[str, Any],
                                 context: Optional[Dict[str, Any]] = None,
                                 page_token: Optional[str] = None,
                                 search: Optional[str] = None) -> Dict[str, Any]:
        try:
            credential = BenchmarkEmailCredential.model_validate(credential_data)
            if field_name == "contact_structure_id":
                result = await _request(credential, "GET", "/api/contact-structure", action="load_contact_structures")
                if result["status"] != "success":
                    return {"options": [], "error": result["error"]}
                records = result["data"] if isinstance(result["data"], list) else []
                return {"options": [{"value": row["_id"], "label": row.get("label") or row["_id"]}
                                    for row in records if isinstance(row, dict) and row.get("_id")]}
            if field_name == "list_id":
                ctx = context or {}
                structure_id = ctx.get("contact_structure_id") or (ctx.get("config") or {}).get("contact_structure_id")
                if not structure_id:
                    return {"options": [], "error": "Select a contact structure first"}
                result = await _request(credential, "GET", f"/api/contact-structure/{_resource_id(str(structure_id))}/lists/all", action="load_lists")
                if result["status"] != "success":
                    return {"options": [], "error": result["error"]}
                data = result["data"]
                records = data.get("records", []) if isinstance(data, dict) else data
                if not isinstance(records, list):
                    records = []
                return {"options": [{"value": row["_id"], "label": row.get("name") or row["_id"]}
                                    for row in records if isinstance(row, dict) and row.get("_id")]}
        except (ValueError, TypeError) as exc:
            return {"options": [], "error": str(exc)}
        return {"options": []}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, BenchmarkEmailNodeConfig):
            raise ValueError("Valid Benchmark Email configuration is required")
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Benchmark Email API key and account API URL")
        op = self.config.config
        name = op.operation

        async def req(method: str, path: str, *, body: Optional[dict] = None,
                      params: Optional[dict] = None) -> dict[str, Any]:
            return await _request(credential, method, path, body=body, params=params, action=name)

        if name == "list_contact_structures":
            return await req("GET", "/api/contact-structure")
        if name == "get_contact_structure":
            return await req("GET", f"/api/contact-structure/{_resource_id(op.contact_structure_id)}")
        if name in {"list_lists", "get_list", "create_list", "rename_list", "duplicate_list", "delete_list", "merge_lists"}:
            base = f"/api/contact-structure/{_resource_id(op.contact_structure_id)}/lists"
            if name == "list_lists":
                return await req("GET", base, params={"page": op.page, "size": op.size, "criteria": op.criteria})
            if name == "create_list":
                return await req("POST", base, body={"name": op.name})
            if name == "merge_lists":
                ids = _id_list(op.list_ids)
                if not ids:
                    raise ValueError("Enter at least one source list ID")
                return await req("POST", f"{base}/merge", body={"name": op.name, "listIds": ids})
            path = f"{base}/{_resource_id(op.list_id)}"
            if name == "get_list":
                return await req("GET", path)
            if name == "delete_list":
                return await req("DELETE", path)
            if name == "duplicate_list":
                return await req("POST", f"{path}/duplicate", body={"name": op.name})
            current = await req("GET", path)
            if current["status"] != "success":
                return current
            return await req("PATCH", path, body={"name": op.name, "__v": current["data"]["__v"]})
        if name == "search_contacts":
            body = {"contactStructureId": _resource_id(op.contact_structure_id),
                    "page": op.page, "pageSize": op.page_size,
                    "source": ["_id", "key", "fields", "lists", "contactStatus", "createdAt"],
                    "contactSpecification": {"filters": [{"criterias": [{
                        "columnToFilter": "KEY", "operator": "EQ", "values": [op.email]
                    }]}]}}
            return await req("POST", "/api/contact/search", body=body)
        if name == "create_contact":
            body = {"key": op.email, "contactStructureId": _resource_id(op.contact_structure_id)}
            if op.fields_json is not None:
                body["fields"] = _fields(op.fields_json)
            if op.list_ids is not None:
                body["lists"] = _csv_ids(op.list_ids)
            return await req("POST", "/api/contact", body=body)
        if name in {"get_contact", "update_contact", "unsubscribe_contact", "delete_contact"}:
            path = f"/api/contact/{_resource_id(op.contact_id)}"
            if name == "get_contact":
                return await req("GET", path)
            if name == "delete_contact":
                return await req("DELETE", path)
            if name == "unsubscribe_contact":
                return await req("PATCH", path, body={"status": {"primary": "Inactive", "secondary": "Unsubscribe"}})
            if op.email is None and op.fields_json is None and op.list_ids is None:
                raise ValueError("Set at least one contact field to update")
            current = await req("GET", path)
            if current["status"] != "success":
                return current
            data = current["data"]
            body = {key: data[key] for key in ("key", "contactStructureId", "fields", "lists", "tags", "status", "__v") if key in data}
            if op.email is not None:
                body["key"] = op.email
            if op.fields_json is not None:
                body["fields"] = _fields(op.fields_json)
            if op.list_ids is not None:
                body["lists"] = _csv_ids(op.list_ids)
            return await req("PUT", path, body=body)
        if name == "list_campaigns":
            return await req("GET", "/api/email/campaign", params={"page": op.page, "size": op.size,
                                                                   "criteria": op.criteria, "statuses": op.statuses})
        if name == "create_campaign":
            return await req("POST", "/api/email/campaign", body=_body_campaign(op))
        if name in {"get_campaign", "update_campaign", "duplicate_campaign", "delete_campaign"}:
            path = f"/api/email/campaign/{_resource_id(op.campaign_id)}"
            if name == "get_campaign":
                return await req("GET", path)
            if name == "delete_campaign":
                return await req("DELETE", path)
            if name == "duplicate_campaign":
                return await req("POST", f"{path}/duplicate", body={"name": op.name})
            body = _body_campaign(op)
            if not body:
                raise ValueError("Set at least one campaign field to update")
            current = await req("GET", path)
            if current["status"] != "success":
                return current
            body["__v"] = current["data"]["__v"]
            return await req("PATCH", path, body=body)
        read_paths = {
            "list_domains": "/api/email/domain", "list_templates": "/api/email/template",
            "dashboard_report": "/api/reports/dashboard",
            "email_overall_report": "/api/reports/email/overall",
        }
        if name in read_paths:
            params = {"pastDays": op.past_days, "timezone": op.timezone} if name in {
                "dashboard_report", "email_overall_report"
            } else None
            if name == "list_templates":
                params = {"lang": op.language}
            return await req("GET", read_paths[name], params=params)
        if name == "email_campaign_report":
            return await req("GET", f"/api/reports/email/{_resource_id(op.campaign_id)}")
        raise ValueError(f"Unknown Benchmark Email operation: {name}")
