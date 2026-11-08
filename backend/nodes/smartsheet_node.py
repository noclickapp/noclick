"""Smartsheet sheets, rows, columns, discussions, and workspaces."""

import json
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.smartsheet import SMARTSHEET_SCOPES

API_BASE = "https://api.smartsheet.com/2.0"


def _operation(name: str, label: str, category: str, **extra: Any) -> Any:
    return Field(name, title=label, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category,
        "x-is-trigger": False, "x-display-name": label, **extra,
    })


def _id_field(resource: str) -> Any:
    extra = {"x-dynamic-options": {
        "field_name": f"{resource}_id", "placeholder": f"Select a {resource}…",
        "searchable": True, "allow_custom": True, "custom_placeholder": f"Or paste {resource} ID",
    }} if resource in ("sheet", "workspace") else None
    return Field(..., title=f"{resource.title()} ID", json_schema_extra=extra)


class SmartsheetOAuthCredential(BaseModel):
    credential_type: Literal["smartsheet_oauth"] = Field("smartsheet_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")
    email: Optional[str] = Field(None, title="Account Email")
    model_config = ConfigDict(json_schema_extra={
        "title": "Smartsheet Account",
        "x-credential-type": "oauth", "x-oauth-provider": "smartsheet",
        "x-oauth-scopes": SMARTSHEET_SCOPES.declared_scopes(),
        "x-credential-url": "https://developers.smartsheet.com/api/smartsheet/guides/advanced-topics/oauth",
    })


class SmartsheetPATCredential(BaseModel):
    credential_type: Literal["smartsheet_pat"] = Field("smartsheet_pat", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="API Access Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(json_schema_extra={
        "title": "Smartsheet API Token", "x-credential-url": "https://app.smartsheet.com/b/account",
    })


SmartsheetCredential = Union[SmartsheetOAuthCredential, SmartsheetPATCredential]


class GetCurrentUser(BaseModel):
    """Identify the connected user."""
    operation: Literal["get_current_user"] = _operation("get_current_user", "Get Current User", "Account")


class ListSheets(BaseModel):
    """List sheets available to the connected user."""
    operation: Literal["list_sheets"] = _operation("list_sheets", "List Sheets", "Sheets")
    page: int = Field(1, ge=1, title="Page")
    page_size: int = Field(100, ge=1, le=1000, title="Page Size")


class GetSheet(BaseModel):
    """Read a sheet, its columns and rows."""
    operation: Literal["get_sheet"] = _operation("get_sheet", "Get Sheet", "Sheets")
    sheet_id: str = _id_field("sheet")
    page: Optional[int] = Field(None, ge=1, title="Row Page")
    page_size: Optional[int] = Field(None, ge=1, le=1000, title="Rows Per Page")


class CreateSheet(BaseModel):
    """Create a sheet in a workspace with its initial columns."""
    operation: Literal["create_sheet"] = _operation("create_sheet", "Create Sheet", "Sheets", **{
        "x-creates-resource": True, "x-resource-type": "smartsheet_sheet", "x-resource-id-path": "data.result.id",
    })
    workspace_id: str = _id_field("workspace")
    name: str = Field(..., min_length=1, title="Sheet Name")
    columns_json: str = Field(..., title="Columns JSON", description='JSON array, for example [{"title":"Task","type":"TEXT_NUMBER","primary":true}]', json_schema_extra={"ui:widget": "textarea"})


class UpdateSheet(BaseModel):
    """Rename a sheet."""
    operation: Literal["update_sheet"] = _operation("update_sheet", "Rename Sheet", "Sheets")
    sheet_id: str = _id_field("sheet")
    name: str = Field(..., min_length=1, title="New Name")


class DeleteSheet(BaseModel):
    """Delete a sheet."""
    operation: Literal["delete_sheet"] = _operation("delete_sheet", "Delete Sheet", "Sheets")
    sheet_id: str = _id_field("sheet")


class ListWorkspaces(BaseModel):
    """List workspaces available to the user."""
    operation: Literal["list_workspaces"] = _operation("list_workspaces", "List Workspaces", "Workspaces")
    page: int = Field(1, ge=1, title="Page")
    page_size: int = Field(100, ge=1, le=1000, title="Page Size")


class GetWorkspace(BaseModel):
    """Read workspace metadata."""
    operation: Literal["get_workspace"] = _operation("get_workspace", "Get Workspace", "Workspaces")
    workspace_id: str = _id_field("workspace")


class GetRow(BaseModel):
    """Read one row with its cells."""
    operation: Literal["get_row"] = _operation("get_row", "Get Row", "Rows")
    sheet_id: str = _id_field("sheet")
    row_id: str = _id_field("row")


class AddRows(BaseModel):
    """Add one or more rows with cell values."""
    operation: Literal["add_rows"] = _operation("add_rows", "Add Rows", "Rows", **{
        "x-creates-resource": True, "x-resource-type": "smartsheet_row", "x-resource-id-path": "data.result.0.id",
    })
    sheet_id: str = _id_field("sheet")
    rows_json: str = Field(..., title="Rows JSON", description='JSON array of rows, each with cells and a location such as {"toBottom":true}', json_schema_extra={"ui:widget": "textarea"})


class UpdateRows(BaseModel):
    """Update rows by ID."""
    operation: Literal["update_rows"] = _operation("update_rows", "Update Rows", "Rows")
    sheet_id: str = _id_field("sheet")
    rows_json: str = Field(..., title="Rows JSON", description="JSON array of row objects with id and cells", json_schema_extra={"ui:widget": "textarea"})


class DeleteRows(BaseModel):
    """Delete rows by their IDs."""
    operation: Literal["delete_rows"] = _operation("delete_rows", "Delete Rows", "Rows")
    sheet_id: str = _id_field("sheet")
    row_ids: str = Field(..., title="Row IDs", description="Comma-separated row IDs")


class ListColumns(BaseModel):
    """List a sheet's columns."""
    operation: Literal["list_columns"] = _operation("list_columns", "List Columns", "Columns")
    sheet_id: str = _id_field("sheet")


class GetColumn(BaseModel):
    """Read a column definition."""
    operation: Literal["get_column"] = _operation("get_column", "Get Column", "Columns")
    sheet_id: str = _id_field("sheet")
    column_id: str = _id_field("column")


class AddColumn(BaseModel):
    """Add a column to a sheet."""
    operation: Literal["add_column"] = _operation("add_column", "Add Column", "Columns", **{
        "x-creates-resource": True, "x-resource-type": "smartsheet_column", "x-resource-id-path": "data.result.0.id",
    })
    sheet_id: str = _id_field("sheet")
    title: str = Field(..., min_length=1, title="Column Title")
    column_type: Literal["TEXT_NUMBER", "DATE", "CHECKBOX", "PICKLIST", "MULTI_PICKLIST", "CONTACT_LIST"] = Field("TEXT_NUMBER", title="Column Type")
    index: int = Field(..., ge=0, title="Column Index")


class UpdateColumn(BaseModel):
    """Update a column title or type."""
    operation: Literal["update_column"] = _operation("update_column", "Update Column", "Columns")
    sheet_id: str = _id_field("sheet")
    column_id: str = _id_field("column")
    title: Optional[str] = Field(None, min_length=1, title="New Title")
    index: Optional[int] = Field(None, ge=0, title="New Index")


class DeleteColumn(BaseModel):
    """Delete a column."""
    operation: Literal["delete_column"] = _operation("delete_column", "Delete Column", "Columns")
    sheet_id: str = _id_field("sheet")
    column_id: str = _id_field("column")


class ListDiscussions(BaseModel):
    """List sheet discussions."""
    operation: Literal["list_discussions"] = _operation("list_discussions", "List Discussions", "Discussions")
    sheet_id: str = _id_field("sheet")


class GetDiscussion(BaseModel):
    """Read a discussion."""
    operation: Literal["get_discussion"] = _operation("get_discussion", "Get Discussion", "Discussions")
    sheet_id: str = _id_field("sheet")
    discussion_id: str = _id_field("discussion")


class CreateDiscussion(BaseModel):
    """Start a discussion on a sheet."""
    operation: Literal["create_discussion"] = _operation("create_discussion", "Create Discussion", "Discussions", **{
        "x-creates-resource": True, "x-resource-type": "smartsheet_discussion", "x-resource-id-path": "data.result.id",
    })
    sheet_id: str = _id_field("sheet")
    comment: str = Field(..., min_length=1, title="Comment", json_schema_extra={"ui:widget": "textarea"})


class CreateComment(BaseModel):
    """Reply to a sheet discussion."""
    operation: Literal["create_comment"] = _operation("create_comment", "Reply to Discussion", "Discussions")
    sheet_id: str = _id_field("sheet")
    discussion_id: str = _id_field("discussion")
    comment: str = Field(..., min_length=1, title="Comment", json_schema_extra={"ui:widget": "textarea"})


SmartsheetConfig = Annotated[Union[
    GetCurrentUser, ListSheets, GetSheet, CreateSheet, UpdateSheet, DeleteSheet,
    ListWorkspaces, GetWorkspace, GetRow, AddRows, UpdateRows, DeleteRows,
    ListColumns, GetColumn, AddColumn, UpdateColumn, DeleteColumn,
    ListDiscussions, GetDiscussion, CreateDiscussion, CreateComment,
], Discriminator("operation")]


class SmartsheetNodeConfig(NodeConfig[SmartsheetConfig, SmartsheetCredential]):
    pass


def _json_payload(raw: str, *, array: bool = True) -> Any:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Enter valid JSON") from exc
    if array and (not isinstance(value, list) or not value or not all(isinstance(item, dict) for item in value)):
        raise ValueError("Enter a non-empty JSON array of objects")
    return value


class SmartsheetNode(WorkflowNode):
    """Execute Smartsheet REST API operations with OAuth or an API token."""

    integration_type = "automation-smartsheet"
    credential_provider_labels = {"smartsheet": "Smartsheet Account"}
    connection_evidence = ConnectionEvidence(operation="list_sheets", noun="sheets", identity_operation="get_current_user")
    scope_registry = SMARTSHEET_SCOPES
    edit_examples = ["List my Smartsheet sheets", "Add a row to a sheet", "Update a row in Smartsheet"]

    @classmethod
    def get_config_model(cls):
        return SmartsheetNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data.get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.smartsheet_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="smartsheet")

    async def _token(self, credential: SmartsheetCredential) -> str:
        data = credential.model_dump()
        if data.get("refresh_token"):
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.smartsheet_oauth import refresh_access_token
            await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
                credential=data, refresh=refresh_access_token, provider="smartsheet", caller_path="execute")
            for key in ("access_token", "refresh_token", "expires_at"):
                setattr(credential, key, data[key])
        return data["access_token"]

    @staticmethod
    async def _request(token: str, method: str, path: str, *, params=None, body=None) -> Any:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(method, f"{API_BASE}{path}",
                params={k: v for k, v in (params or {}).items() if v is not None}, json=body,
                headers={"Authorization": f"Bearer {token}"})
        if response.is_error:
            try:
                error = response.json()
                detail = error.get("message") or error.get("errorCode")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Smartsheet API error {response.status_code}: {detail or 'request failed'}")
        return response.json() if response.content else {"ok": True}

    @classmethod
    async def load_field_options(
        cls, field_name: str, credential_data: dict, context=None,
        page_token: Optional[str] = None, search: Optional[str] = None,
    ) -> list[dict]:
        if field_name not in ("sheet_id", "workspace_id"):
            return []
        path = "/sheets" if field_name == "sheet_id" else "/workspaces"
        try:
            page = max(1, int(page_token)) if page_token else 1
        except ValueError as exc:
            raise ValueError("Invalid page token") from exc
        payload = await cls._request(credential_data["access_token"], "GET", path, params={"pageSize": 100, "page": page})
        return [{"value": str(item["id"]), "label": item.get("name") or str(item["id"])}
                for item in payload.get("data", []) if item.get("id") and (
                    not search or search.casefold() in (item.get("name") or "").casefold())]

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, SmartsheetNodeConfig):
            raise ValueError("Smartsheet configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Smartsheet account or enter an API token")
        op = self.config.config
        self.scope_registry.require(op.operation)
        token = await self._token(credential)
        sheet = f"/sheets/{quote(op.sheet_id, safe='')}" if hasattr(op, "sheet_id") else ""
        workspace = f"/workspaces/{quote(op.workspace_id, safe='')}" if hasattr(op, "workspace_id") else ""
        method, path, params, body = "GET", "", None, None
        if isinstance(op, GetCurrentUser):
            path = "/users/me"
        elif isinstance(op, ListSheets):
            path, params = "/sheets", {"page": op.page, "pageSize": op.page_size}
        elif isinstance(op, GetSheet):
            path, params = sheet, {"page": op.page, "pageSize": op.page_size}
        elif isinstance(op, CreateSheet):
            method, path = "POST", f"{workspace}/sheets"
            body = {"name": op.name, "columns": _json_payload(op.columns_json)}
        elif isinstance(op, UpdateSheet):
            method, path, body = "PUT", sheet, {"name": op.name}
        elif isinstance(op, DeleteSheet):
            method, path = "DELETE", sheet
        elif isinstance(op, ListWorkspaces):
            path, params = "/workspaces", {"page": op.page, "pageSize": op.page_size}
        elif isinstance(op, GetWorkspace):
            path = f"{workspace}/metadata"
        elif isinstance(op, GetRow):
            path = f"{sheet}/rows/{quote(op.row_id, safe='')}"
        elif isinstance(op, AddRows):
            method, path, body = "POST", f"{sheet}/rows", _json_payload(op.rows_json)
        elif isinstance(op, UpdateRows):
            method, path, body = "PUT", f"{sheet}/rows", _json_payload(op.rows_json)
        elif isinstance(op, DeleteRows):
            ids = [item.strip() for item in op.row_ids.split(",") if item.strip()]
            if not ids:
                raise ValueError("Enter at least one row ID")
            method, path, params = "DELETE", f"{sheet}/rows", {"ids": ",".join(ids)}
        elif isinstance(op, ListColumns):
            path = f"{sheet}/columns"
        elif isinstance(op, GetColumn):
            path = f"{sheet}/columns/{quote(op.column_id, safe='')}"
        elif isinstance(op, AddColumn):
            method, path = "POST", f"{sheet}/columns"
            body = [{"title": op.title, "type": op.column_type, "index": op.index}]
        elif isinstance(op, UpdateColumn):
            method, path = "PUT", f"{sheet}/columns/{quote(op.column_id, safe='')}"
            body = op.model_dump(exclude={"operation", "sheet_id", "column_id"}, exclude_none=True)
            if not body:
                raise ValueError("Provide a title or index to update")
        elif isinstance(op, DeleteColumn):
            method, path = "DELETE", f"{sheet}/columns/{quote(op.column_id, safe='')}"
        elif isinstance(op, ListDiscussions):
            path = f"{sheet}/discussions"
        elif isinstance(op, GetDiscussion):
            path = f"{sheet}/discussions/{quote(op.discussion_id, safe='')}"
        elif isinstance(op, CreateDiscussion):
            method, path, body = "POST", f"{sheet}/discussions", {"comment": {"text": op.comment}}
        elif isinstance(op, CreateComment):
            method, path, body = "POST", f"{sheet}/discussions/{quote(op.discussion_id, safe='')}/comments", {"text": op.comment}
        else:
            raise ValueError(f"Unsupported Smartsheet operation: {op.operation}")
        result = await self._request(token, method, path, params=params, body=body)
        return {"status": "success", "operation": op.operation, "data": result}
