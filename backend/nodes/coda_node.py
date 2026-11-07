"""Coda docs, pages, tables, rows, formulas, controls, folders and sharing.

Routes follow Coda's official OpenAPI 3 spec:
https://coda.io/apis/v1/openapi.json
"""

import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    fields: dict[str, tuple[Any, Any]]
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    creates: Optional[str] = None


def text_field(title: str, *, required: bool = False, description: str = "", multiline: bool = False):
    return (str if required else Optional[str], Field(
        ... if required else None, title=title, description=description,
        json_schema_extra={"ui:widget": "textarea"} if multiline else None))


def int_field(title: str):
    return (Optional[int], Field(None, title=title, ge=1, le=500))


def bool_field(title: str):
    return (Optional[bool], Field(None, title=title))


DOC = {"doc_id": (str, Field(
    ..., title="Doc ID", description="The stable ID from a Coda doc URL",
    json_schema_extra={"x-dynamic-options": {
        "field_name": "doc_id", "placeholder": "Select a doc...", "searchable": True,
        "allow_custom": True, "custom_placeholder": "Or paste a doc ID"},
        "x-resource-type": "coda_doc"}))}
PAGE = {"page_id": text_field("Page ID", required=True)}
TABLE = {"table_id": (str, Field(
    ..., title="Table ID", json_schema_extra={"x-dynamic-options": {
        "field_name": "table_id", "placeholder": "Select a table...", "searchable": True,
        "allow_custom": True, "custom_placeholder": "Or paste a table ID",
        "depends_on": "doc_id"}, "x-resource-type": "coda_table"}))}
ROW = {"row_id": text_field("Row ID", required=True)}
COLUMN = {"column_id": text_field("Column ID", required=True)}
FOLDER = {"folder_id": text_field("Folder ID", required=True)}
PAGING = {"limit": int_field("Page Size"), "page_token": text_field("Page Token")}


OPERATIONS: dict[str, Operation] = {
    "get_current_user": Operation("Get Current User", "Account", "GET", "/whoami", {}),
    "list_docs": Operation("List Docs", "Docs", "GET", "/docs", {
        **PAGING, "query": text_field("Search Query"), "workspace_id": text_field("Workspace ID"),
        "folder_id": text_field("Folder ID"), "is_owner": bool_field("Owned by Me")},
        query=("limit", "page_token", "query", "workspace_id", "folder_id", "is_owner")),
    "get_doc": Operation("Get Doc", "Docs", "GET", "/docs/{doc_id}", DOC),
    "create_doc": Operation("Create Doc", "Docs", "POST", "/docs", {
        "title": text_field("Title", required=True), "source_doc": text_field("Copy From Doc ID"),
        "folder_id": text_field("Folder ID")}, body=("title", "source_doc", "folder_id"), creates="doc"),
    "update_doc": Operation("Update Doc", "Docs", "PATCH", "/docs/{doc_id}", {
        **DOC, "title": text_field("Title"), "icon_name": text_field("Icon Name")}, body=("title", "icon_name")),
    "delete_doc": Operation("Delete Doc", "Docs", "DELETE", "/docs/{doc_id}", DOC),
    "publish_doc": Operation("Publish Doc", "Docs", "PUT", "/docs/{doc_id}/publish", {
        **DOC, "slug": text_field("Public Slug"), "discoverable": bool_field("Discoverable"),
        "category_names_json": text_field("Category Names JSON", multiline=True,
            description='Optional array such as ["Project management"]'),
        "mode": text_field("Publish Mode")},
        body=("slug", "discoverable", "category_names_json", "mode")),
    "unpublish_doc": Operation("Unpublish Doc", "Docs", "DELETE", "/docs/{doc_id}/publish", DOC),
    "list_pages": Operation("List Pages", "Pages", "GET", "/docs/{doc_id}/pages", {
        **DOC, **PAGING}, query=("limit", "page_token")),
    "get_page": Operation("Get Page", "Pages", "GET", "/docs/{doc_id}/pages/{page_id}", {**DOC, **PAGE}),
    "create_page": Operation("Create Page", "Pages", "POST", "/docs/{doc_id}/pages", {
        **DOC, "name": text_field("Page Name", required=True), "subtitle": text_field("Subtitle"),
        "parent_page_id": text_field("Parent Page ID")},
        body=("name", "subtitle", "parent_page_id"), creates="page"),
    "update_page": Operation("Update Page", "Pages", "PUT", "/docs/{doc_id}/pages/{page_id}", {
        **DOC, **PAGE, "name": text_field("Page Name"), "subtitle": text_field("Subtitle"),
        "is_hidden": bool_field("Hidden")}, body=("name", "subtitle", "is_hidden")),
    "delete_page": Operation("Delete Page", "Pages", "DELETE", "/docs/{doc_id}/pages/{page_id}", {**DOC, **PAGE}),
    "list_page_content": Operation("List Page Content", "Pages", "GET", "/docs/{doc_id}/pages/{page_id}/content", {
        **DOC, **PAGE, **PAGING}, query=("limit", "page_token")),
    "delete_page_content": Operation("Delete Page Content", "Pages", "DELETE", "/docs/{doc_id}/pages/{page_id}/content", {
        **DOC, **PAGE, "element_ids_json": text_field("Element IDs JSON", required=True, multiline=True,
            description="Array of element IDs to delete; [] deletes all content")},
        body=("element_ids_json",)),
    "begin_page_export": Operation("Export Page Content", "Pages", "POST", "/docs/{doc_id}/pages/{page_id}/export", {
        **DOC, **PAGE, "output_format": text_field("Output Format", required=True, description="html or markdown")},
        body=("output_format",)),
    "get_export_status": Operation("Get Page Export Status", "Pages", "GET", "/docs/{doc_id}/pages/{page_id}/export/{request_id}", {
        **DOC, **PAGE, "request_id": text_field("Export Request ID", required=True)}),
    "list_tables": Operation("List Tables", "Tables", "GET", "/docs/{doc_id}/tables", {
        **DOC, **PAGING}, query=("limit", "page_token")),
    "get_table": Operation("Get Table", "Tables", "GET", "/docs/{doc_id}/tables/{table_id}", {**DOC, **TABLE}),
    "list_columns": Operation("List Columns", "Tables", "GET", "/docs/{doc_id}/tables/{table_id}/columns", {
        **DOC, **TABLE, **PAGING}, query=("limit", "page_token")),
    "get_column": Operation("Get Column", "Tables", "GET", "/docs/{doc_id}/tables/{table_id}/columns/{column_id}", {
        **DOC, **TABLE, **COLUMN}),
    "list_rows": Operation("List Rows", "Rows", "GET", "/docs/{doc_id}/tables/{table_id}/rows", {
        **DOC, **TABLE, **PAGING, "query": text_field("Row Filter", description='For example c-abc:"Apple"'),
        "value_format": text_field("Value Format", description="simple, simpleWithArrays, or rich"),
        "visible_only": bool_field("Visible Rows Only")},
        query=("limit", "page_token", "query", "value_format", "visible_only")),
    "get_row": Operation("Get Row", "Rows", "GET", "/docs/{doc_id}/tables/{table_id}/rows/{row_id}", {
        **DOC, **TABLE, **ROW, "value_format": text_field("Value Format")}, query=("value_format",)),
    "upsert_rows": Operation("Insert or Upsert Rows", "Rows", "POST", "/docs/{doc_id}/tables/{table_id}/rows", {
        **DOC, **TABLE, "rows_json": text_field("Rows JSON", required=True, multiline=True,
            description='Array of {"cells":[{"column":"c-...","value":"..."}]} objects'),
        "key_columns_json": text_field("Key Columns JSON", multiline=True,
            description="Optional array of column IDs for upsert matching")},
        body=("rows_json", "key_columns_json")),
    "update_row": Operation("Update Row", "Rows", "PUT", "/docs/{doc_id}/tables/{table_id}/rows/{row_id}", {
        **DOC, **TABLE, **ROW, "row_json": text_field("Row JSON", required=True, multiline=True,
            description='An object containing cells: {"cells":[{"column":"c-...","value":"..."}]}')},
        body=("row_json",)),
    "delete_row": Operation("Delete Row", "Rows", "DELETE", "/docs/{doc_id}/tables/{table_id}/rows/{row_id}", {
        **DOC, **TABLE, **ROW}),
    "delete_rows": Operation("Delete Rows", "Rows", "DELETE", "/docs/{doc_id}/tables/{table_id}/rows", {
        **DOC, **TABLE, "row_ids_json": text_field("Row IDs JSON", required=True, multiline=True,
            description="Array of row IDs to delete")}, body=("row_ids_json",)),
    "push_button": Operation("Push Row Button", "Rows", "POST", "/docs/{doc_id}/tables/{table_id}/rows/{row_id}/buttons/{column_id}", {
        **DOC, **TABLE, **ROW, **COLUMN}),
    "list_formulas": Operation("List Formulas", "Formulas & Controls", "GET", "/docs/{doc_id}/formulas", {
        **DOC, **PAGING}, query=("limit", "page_token")),
    "get_formula": Operation("Get Formula", "Formulas & Controls", "GET", "/docs/{doc_id}/formulas/{formula_id}", {
        **DOC, "formula_id": text_field("Formula ID", required=True)}),
    "list_controls": Operation("List Controls", "Formulas & Controls", "GET", "/docs/{doc_id}/controls", {
        **DOC, **PAGING}, query=("limit", "page_token")),
    "get_control": Operation("Get Control", "Formulas & Controls", "GET", "/docs/{doc_id}/controls/{control_id}", {
        **DOC, "control_id": text_field("Control ID", required=True)}),
    "list_folders": Operation("List Folders", "Folders", "GET", "/folders", {
        **PAGING, "workspace_id": text_field("Workspace ID")}, query=("limit", "page_token", "workspace_id")),
    "get_folder": Operation("Get Folder", "Folders", "GET", "/folders/{folder_id}", FOLDER),
    "list_folder_children": Operation("List Folder Children", "Folders", "GET", "/folders/{folder_id}/children", {
        **FOLDER, **PAGING}, query=("limit", "page_token")),
    "create_folder": Operation("Create Folder", "Folders", "POST", "/folders", {
        "workspace_id": text_field("Workspace ID", required=True), "name": text_field("Folder Name", required=True),
        "description": text_field("Description")}, body=("workspace_id", "name", "description"), creates="folder"),
    "update_folder": Operation("Update Folder", "Folders", "PATCH", "/folders/{folder_id}", {
        **FOLDER, "name": text_field("Folder Name"), "description": text_field("Description")},
        body=("name", "description")),
    "delete_folder": Operation("Delete Folder", "Folders", "DELETE", "/folders/{folder_id}", FOLDER),
    "list_permissions": Operation("List Doc Permissions", "Sharing", "GET", "/docs/{doc_id}/acl/permissions", {
        **DOC, **PAGING}, query=("limit", "page_token")),
    "get_sharing_metadata": Operation("Get Sharing Metadata", "Sharing", "GET", "/docs/{doc_id}/acl/metadata", DOC),
    "search_principals": Operation("Search Share Recipients", "Sharing", "GET", "/docs/{doc_id}/acl/principals/search", {
        **DOC, "query": text_field("Name or Email", required=True)}, query=("query",)),
    "get_sharing_settings": Operation("Get Sharing Settings", "Sharing", "GET", "/docs/{doc_id}/acl/settings", DOC),
    "update_sharing_settings": Operation("Update Sharing Settings", "Sharing", "PATCH", "/docs/{doc_id}/acl/settings", {
        **DOC, "allow_editors_to_change_permissions": bool_field("Editors Can Share"),
        "allow_copying": bool_field("Allow Copying"),
        "allow_viewers_to_request_editing": bool_field("Viewers Can Request Editing")},
        body=("allow_editors_to_change_permissions", "allow_copying", "allow_viewers_to_request_editing")),
    "add_permission": Operation("Add Doc Permission", "Sharing", "POST", "/docs/{doc_id}/acl/permissions", {
        **DOC, "access": text_field("Access", required=True, description="readonly, write, or comment"),
        "principal_json": text_field("Principal JSON", required=True, multiline=True,
            description='For example {"type":"email","email":"teammate@example.com"}'),
        "suppress_email": bool_field("Suppress Invite Email")},
        body=("access", "principal_json", "suppress_email"), creates="permission"),
    "delete_permission": Operation("Remove Doc Permission", "Sharing", "DELETE", "/docs/{doc_id}/acl/permissions/{permission_id}", {
        **DOC, "permission_id": text_field("Permission ID", required=True)}),
    "get_mutation_status": Operation("Get Mutation Status", "Utilities", "GET", "/mutationStatus/{request_id}", {
        "request_id": text_field("Request ID", required=True)}),
    "trigger_automation": Operation("Trigger Doc Automation", "Utilities", "POST", "/docs/{doc_id}/hooks/automation/{rule_id}", {
        **DOC, "rule_id": text_field("Automation Rule ID", required=True),
        "payload_json": text_field("Payload JSON", required=True, multiline=True,
            description="JSON object delivered to the webhook-invoked rule")}, body=("payload_json",)),
    "resolve_browser_link": Operation("Resolve Browser Link", "Utilities", "GET", "/resolveBrowserLink", {
        "url": text_field("Coda URL", required=True),
        "degrade_gracefully": bool_field("Degrade Gracefully")}, query=("url", "degrade_gracefully")),
}


class CodaAPITokenCredential(BaseModel):
    credential_type: Literal["coda_api_token"] = Field("coda_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Coda API Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Coda API Token", json_schema_extra={
        "x-credential-url": "https://coda.io/account",
        "x-credential-instructions": "Open your Coda account settings and generate an API token. Paste that token here to connect your docs and tables.",
    })


def _make_config(name: str, spec: Operation) -> type[BaseModel]:
    model_name = "Coda" + "".join(part.title() for part in name.split("_")) + "Config"
    extra: dict[str, Any] = {"const": name, "ui:hidden": True, "x-category": spec.category,
                             "x-is-trigger": False, "x-display-name": spec.label}
    if spec.creates:
        extra.update({"x-creates-resource": True, "x-resource-type": f"coda_{spec.creates}",
                      "x-resource-id-path": "data.id"})
    return create_model(model_name, __module__=__name__,
                        operation=(Literal[name], Field(name, title=spec.label, json_schema_extra=extra)),
                        **spec.fields)


CONFIG_MODELS = {name: _make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
CodaConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class CodaNodeConfig(NodeConfig[CodaConfig, CodaAPITokenCredential]):
    pass


def _api_name(name: str) -> str:
    name = name.removesuffix("_json")
    head, *parts = name.split("_")
    return head + "".join(part.title() for part in parts)


class CodaNode(WorkflowNode):
    integration_type = "automation-coda"
    connection_evidence = ConnectionEvidence(field="doc_id", noun="docs", identity_operation="get_current_user")
    edit_examples = [
        "Read rows from a Coda table", "Upsert rows in a Coda doc",
        "Create a Coda page", "List docs and folders", "Push a row button",
    ]

    @classmethod
    def get_config_model(cls):
        return CodaNodeConfig

    @classmethod
    async def load_field_options(
        cls, field_name: str, credential_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None, page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> dict[str, Any]:
        if field_name not in ("doc_id", "table_id"):
            return {"options": []}
        token = (credential_data or {}).get("api_token")
        if not token:
            raise ValueError("Connect a Coda API token to list docs and tables")
        context = context or {}
        config = context.get("config") if isinstance(context.get("config"), dict) else context
        if field_name == "doc_id":
            path, params = "/docs", {"limit": 100, "query": search, "pageToken": page_token}
        else:
            doc_id = config.get("doc_id")
            if not doc_id:
                return {"options": []}
            path, params = f"/docs/{quote(str(doc_id), safe='')}/tables", {"limit": 100, "pageToken": page_token}
        data = await cls._request(token, "GET", path,
                                  params={key: value for key, value in params.items() if value is not None})
        return {
            "options": [{"value": item["id"], "label": item.get("name") or item.get("title") or item["id"]}
                        for item in data.get("items", []) if isinstance(item, dict) and item.get("id")],
            "next_page_token": data.get("nextPageToken"),
        }

    @staticmethod
    async def _request(token: str, method: str, path: str, *, params=None, body=None) -> Any:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(
                method, f"https://docs.superhuman.com/apis/v1{path}", params=params, json=body,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if response.is_error:
            try:
                detail = response.json().get("message") or response.json().get("error")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Coda API error {response.status_code}: {detail or 'request failed'}")
        return response.json() if response.content else {"ok": True}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, CodaNodeConfig):
            raise ValueError("Coda configuration required")
        if not self.config.credentials:
            raise ValueError("Connect a Coda API token")
        op = self.config.config
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude={"operation"}, exclude_none=True)
        path = spec.path
        for key in tuple(values):
            marker = "{" + key + "}"
            if marker in path:
                path = path.replace(marker, quote(str(values.pop(key)), safe=""))
        params = {_api_name(key): values[key] for key in spec.query if key in values}
        body = {}
        for key in spec.body:
            if key not in values:
                continue
            value = values[key]
            if key.endswith("_json"):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{key} must contain valid JSON") from exc
            body[_api_name(key)] = value
        if op.operation == "upsert_rows":
            if not isinstance(body.get("rows"), list):
                raise ValueError("Rows JSON must be an array")
            if "keyColumns" in body and not isinstance(body["keyColumns"], list):
                raise ValueError("Key Columns JSON must be an array")
        if op.operation == "update_row" and not isinstance(body.get("row"), dict):
            raise ValueError("Row JSON must be an object")
        if op.operation == "delete_rows" and not isinstance(body.get("rowIds"), list):
            raise ValueError("Row IDs JSON must be an array")
        if op.operation in ("publish_doc", "delete_page_content"):
            key = "categoryNames" if op.operation == "publish_doc" else "elementIds"
            if key in body and not isinstance(body[key], list):
                raise ValueError(f"{key} must be a JSON array")
        if op.operation == "trigger_automation":
            body = body["payload"]
            if not isinstance(body, dict):
                raise ValueError("Payload JSON must be an object")
        data = await self._request(
            self.config.credentials.api_token, spec.method, path,
            params=params or None, body=body if spec.body else None)
        return {"status": "success", "operation": op.operation, "data": data}
