"""DealMachine public API v1: explicit, single-request CRM operations.

Contract: https://api.docs.dealmachine.com/api-reference/openapi.json (1.0.0).
Pagination is explicit; provider envelopes (including credits) are preserved.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://api.v2.dealmachine.com"
Id = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
RecordId = Annotated[str, Field(pattern=r"^[1-9][0-9]*$", description="Positive decimal record ID; strings preserve large person IDs.")]
Lifecycle = Literal["active", "opportunity", "archived"]


class DealMachineAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="DealMachine API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.docs.dealmachine.com",
            "x-credential-instructions": "Create an API key in the DealMachine developer portal and paste it here. The key is sent as a Bearer token. Connection reads your workspace account. Property lookups and searches can consume data credits; adding prospects uses your prospect allowance.",
        })
    credential_type: Literal["dealmachine_api_key"] = Field("dealmachine_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(Input):
    page: int = Field(1, ge=1, description="Page to read; each run fetches one page.")
    per_page: int = Field(25, ge=1, le=100)


class GetAccount(Input):
    operation: Literal["get_account"] = "get_account"


class SearchProperties(Page):
    """Search property records within a ZIP code; data credits may apply."""
    operation: Literal["search_properties"] = "search_properties"
    zip_code: str = Field(..., pattern=r"^[0-9]{5}$")
    fields: list[str] | None = Field(None, description="Property field IDs from the provider field catalog.")
    result_session_id: str | None = Field(None, max_length=128, description="Copy the previous page's result session unchanged.")


class GetProperty(Input):
    """Read a property; enrichment can consume credits."""
    operation: Literal["get_property"] = "get_property"
    property_id: Id
    enrich: StrictBool = Field(False, description="Enable paid enrichment; false returns base fields.")
    contact_audience: Literal["owners", "owners_and_family", "renters", "residents", "all", "none"] = "none"
    fields: str | None = Field(None, description="Comma-separated property field IDs.")


class ListProspects(Page):
    operation: Literal["list_prospects"] = "list_prospects"
    record_type: Literal["property", "person"] = "property"
    lifecycle: Lifecycle = "active"
    search: str | None = Field(None, max_length=120)
    tag_id: Id | None = None
    list_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    sort: Literal["newest", "oldest"] = "newest"


class AddProspects(Input):
    """Track records as prospects; consumes prospect allowance."""
    operation: Literal["add_prospects"] = "add_prospects"
    record_type: Literal["property", "person", "company"] = "property"
    record_ids: list[Id] = Field(..., min_length=1, max_length=1000)
    favorite: StrictBool = False


class Prospect(Input):
    prospect_id: Id


class GetProspect(Prospect):
    operation: Literal["get_prospect"] = "get_prospect"


class UpdateProspect(Prospect):
    operation: Literal["update_prospect"] = "update_prospect"
    lifecycle: Lifecycle
    favorite: StrictBool | None = None
    cascade: StrictBool = Field(True, description="Archiving removes list memberships and closes opportunities; mail always ends.")


class ArchiveProspect(Prospect):
    operation: Literal["archive_prospect"] = "archive_prospect"
    cascade: StrictBool = Field(True, description="Provider archive cascade; mail always ends.")


class ListProspectNotes(Prospect, Page):
    operation: Literal["list_prospect_notes"] = "list_prospect_notes"


class AddProspectNote(Prospect):
    operation: Literal["add_prospect_note"] = "add_prospect_note"
    body: str = Field(..., min_length=1, max_length=10000)


class ListLists(Page):
    operation: Literal["list_lists"] = "list_lists"
    search: str | None = None
    source_type: Literal["properties", "people"] | None = None
    sort: Literal["newest", "oldest", "name", "name_desc", "count", "count_asc"] = "newest"


class CreateList(Input):
    operation: Literal["create_list"] = "create_list"
    name: str = Field(..., min_length=1, max_length=100)
    source_type: Literal["properties", "people"] = "properties"


class SelectedList(Input):
    list_id: Id


class GetList(SelectedList):
    operation: Literal["get_list"] = "get_list"


class RenameList(SelectedList):
    operation: Literal["rename_list"] = "rename_list"
    name: str = Field(..., min_length=1, max_length=100)


class ListListItems(SelectedList, Page):
    operation: Literal["list_list_items"] = "list_list_items"


class ListItems(SelectedList):
    ids: list[RecordId] = Field(..., min_length=1, max_length=10000)
    id_type: Literal["internal_property_id", "internal_person_id"] = "internal_property_id"


class AddListItems(ListItems):
    operation: Literal["add_list_items"] = "add_list_items"
    add_as_prospects: StrictBool = Field(True, description="Also track records as prospects; counts toward prospect allowance.")


class RemoveListItems(ListItems):
    operation: Literal["remove_list_items"] = "remove_list_items"


class ListTasks(Page):
    operation: Literal["list_tasks"] = "list_tasks"
    status: Literal["open", "completed", "all"] = "all"
    search: str | None = None
    assigned_to_user_id: str | None = None


class CreateTask(Input):
    operation: Literal["create_task"] = "create_task"
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(None, max_length=5000)
    opportunity_id: Id | None = None
    property_id: Id | None = None
    person_id: Id | None = None
    assigned_to_user_id: int | None = None
    due_date: str | None = None


class Task(Input):
    task_id: Id


class GetTask(Task):
    operation: Literal["get_task"] = "get_task"


class UpdateTask(Task):
    """Edit supplied task fields; use clear_fields to explicitly send null."""
    operation: Literal["update_task"] = "update_task"
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=5000)
    opportunity_id: Id | None = None
    property_id: Id | None = None
    person_id: Id | None = None
    assigned_to_user_id: int | None = None
    due_date: str | None = None
    is_completed: StrictBool | None = None
    sort_order: int | None = None
    clear_fields: list[Literal["description", "opportunity_id", "property_id", "person_id", "assigned_to_user_id", "due_date"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def changes(self):
        supplied = self.model_dump(exclude_none=True, exclude={"operation", "task_id", "clear_fields"})
        if not supplied and not self.clear_fields:
            raise ValueError("Supply a task field to update or clear")
        if set(supplied) & set(self.clear_fields):
            raise ValueError("A task field cannot be set and cleared together")
        return self


class DeleteTask(Task):
    operation: Literal["delete_task"] = "delete_task"


class ListTags(Input):
    operation: Literal["list_tags"] = "list_tags"
    include_inactive: StrictBool = False


class CreateTag(Input):
    operation: Literal["create_tag"] = "create_tag"
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=255)
    badge_variant: Literal["default", "secondary", "info", "warning", "destructive"] | None = None
    sort_order: int | None = Field(None, ge=0, le=65535)


class AddProspectTag(Prospect):
    operation: Literal["add_prospect_tag"] = "add_prospect_tag"
    tag_id: Id


DealMachineConfig = Annotated[Union[
    GetAccount, SearchProperties, GetProperty, ListProspects, AddProspects, GetProspect,
    UpdateProspect, ArchiveProspect, ListProspectNotes, AddProspectNote, ListLists,
    CreateList, GetList, RenameList, ListListItems, AddListItems, RemoveListItems,
    ListTasks, CreateTask, GetTask, UpdateTask, DeleteTask, ListTags, CreateTag, AddProspectTag,
], Field(discriminator="operation")]


class DealMachineFullConfig(NodeConfig[DealMachineConfig, DealMachineAPIKeyCredential]):
    pass


# Each operation is exactly one published method + route, with no implicit reads,
# writes, retry or pagination. Path placeholders refer to typed config fields.
ROUTES = {
    "get_account": ("GET", "/v1/account", False),
    "search_properties": ("POST", "/v1/properties/search", True),
    "get_property": ("GET", "/v1/properties/{property_id}", False),
    "list_prospects": ("GET", "/v1/prospects", False),
    "add_prospects": ("POST", "/v1/prospects", True),
    "get_prospect": ("GET", "/v1/prospects/{prospect_id}", False),
    "update_prospect": ("PATCH", "/v1/prospects/{prospect_id}", True),
    "archive_prospect": ("DELETE", "/v1/prospects/{prospect_id}", False),
    "list_prospect_notes": ("GET", "/v1/prospects/{prospect_id}/notes", False),
    "add_prospect_note": ("POST", "/v1/prospects/{prospect_id}/notes", True),
    "list_lists": ("GET", "/v1/lists", False),
    "create_list": ("POST", "/v1/lists", True),
    "get_list": ("GET", "/v1/lists/{list_id}", False),
    "rename_list": ("PATCH", "/v1/lists/{list_id}", True),
    "list_list_items": ("GET", "/v1/lists/{list_id}/items", False),
    "add_list_items": ("POST", "/v1/lists/{list_id}/items", True),
    "remove_list_items": ("DELETE", "/v1/lists/{list_id}/items", True),
    "list_tasks": ("GET", "/v1/tasks", False),
    "create_task": ("POST", "/v1/tasks", True),
    "get_task": ("GET", "/v1/tasks/{task_id}", False),
    "update_task": ("PATCH", "/v1/tasks/{task_id}", True),
    "delete_task": ("DELETE", "/v1/tasks/{task_id}", False),
    "list_tags": ("GET", "/v1/tags", False),
    "create_tag": ("POST", "/v1/tags", True),
    "add_prospect_tag": ("POST", "/v1/prospects/{prospect_id}/tags/{tag_id}", False),
}


class DealMachineNode(WorkflowNode):
    integration_type = "automation-dealmachine"
    connection_evidence = ConnectionEvidence(noun="DealMachine workspace", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return DealMachineFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a DealMachine API key")
        op = self.config.config
        token = self.config.credentials.api_key
        method, path, has_body = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for field in ("property_id", "prospect_id", "list_id", "task_id", "tag_id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        if isinstance(op, SearchProperties):
            values["locations"] = [{"type": "zip_code", "code": values.pop("zip_code")}]
            values.update(anchor="properties", contact_audience="none")
        if isinstance(op, UpdateTask):
            for field in values.pop("clear_fields"):
                values[field] = None
        kwargs = {"json": values} if has_body else {"params": {k: str(v).lower() if type(v) is bool else v for k, v in values.items()}}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
            try:
                body = response.json()
            except ValueError:
                body = None
            if response.status_code not in {200, 201} or isinstance(body, dict) and "error" in body:
                error = body.get("error") if isinstance(body, dict) else None
                message = error.get("message") if isinstance(error, dict) else None
                return {"status": "error", "http_status": response.status_code,
                    "error": str(message or "DealMachine did not confirm the request").replace(token, "[redacted]")}
            if not isinstance(body, dict) or "data" not in body or not isinstance(body["data"], (dict, list)):
                raise ValueError("Expected a DealMachine data envelope")
            if isinstance(op, GetAccount):
                organization = body["data"].get("organization") if isinstance(body["data"], dict) else None
                if not isinstance(organization, dict) or not isinstance(organization.get("name"), str) or not organization["name"].strip() or organization.get("id") is None:
                    raise ValueError("Expected the authenticated DealMachine workspace")
            # Preserve provider records, pagination, search sessions and credit usage.
            # Never return a credential even if a provider unexpectedly echoes it.
            body = json.loads(json.dumps(body).replace(token, "[redacted]"))
            return {**body, "status": "success"}
        except (httpx.HTTPError, SSRFError):
            return {"status": "error", "error": "DealMachine request failed; inspect writes before retrying"}
        except ValueError:
            return {"status": "error", "error": "DealMachine returned an invalid data envelope; inspect writes before retrying"}
