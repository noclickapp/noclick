"""SharePoint sites, lists, list items, and document libraries via Microsoft Graph.

This is the delegated (signed-in user) surface. It deliberately does not expose
tenant administration or app-only operations through a user OAuth credential.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, Dict, Literal, Optional, Type, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_refresh import ensure_fresh_oauth_token, freshen_oauth_credential
from nodes.oauth.microsoft_oauth import refresh_access_token
from nodes.scopes.microsoft_sharepoint import SHAREPOINT_SCOPES

GRAPH = "https://graph.microsoft.com/v1.0"


def _id(value: str) -> str:
    """Keep caller supplied IDs inside one Graph path segment."""
    if not value or not value.strip():
        raise ValueError("A SharePoint resource ID is required")
    return quote(value.strip(), safe="")


def _file_path(value: str) -> str:
    """Encode path segments without allowing a traversal out of a drive root."""
    parts = value.strip("/").split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError("File path must be a nonempty path within the library")
    return "/".join(quote(part, safe="") for part in parts)


def _without_download_urls(value: Any) -> Any:
    """Graph's temporary preauthenticated links should not enter saved run output."""
    if isinstance(value, dict):
        return {
            key: _without_download_urls(item)
            for key, item in value.items()
            if key != "@microsoft.graph.downloadUrl"
        }
    if isinstance(value, list):
        return [_without_download_urls(item) for item in value]
    return value


def _operation(name: str, category: str, title: str):
    return Field(
        name,
        title=title,
        json_schema_extra={
            "const": name,
            "ui:hidden": True,
            "x-category": category,
            "x-display-name": title,
            "x-is-trigger": False,
        },
    )


class SharePointOAuthCredential(BaseModel):
    credential_type: Literal["microsoft_sharepoint_oauth"] = Field(
        "microsoft_sharepoint_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str
    refresh_token: str
    expires_at: str
    email: str

    model_config = ConfigDict(title="Microsoft 365 Account", json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "sharepoint",
        "x-oauth-scopes": [
            "https://graph.microsoft.com/Sites.ReadWrite.All",
            "https://graph.microsoft.com/User.Read",
            "offline_access",
        ],
    })


class GetRootSite(BaseModel):
    operation: Literal["get_root_site"] = _operation("get_root_site", "Site", "Get Root Site")


class SearchSites(BaseModel):
    operation: Literal["search_sites"] = _operation("search_sites", "Site", "Search Sites")
    query: str = Field(..., min_length=1, title="Search Text")


class GetSite(BaseModel):
    operation: Literal["get_site"] = _operation("get_site", "Site", "Get Site")
    site_id: str = Field(..., title="Site ID")


class ListLists(BaseModel):
    operation: Literal["list_lists"] = _operation("list_lists", "List", "List Lists")
    site_id: str = Field(..., title="Site ID")


class GetList(BaseModel):
    operation: Literal["get_list"] = _operation("get_list", "List", "Get List")
    site_id: str = Field(..., title="Site ID")
    list_id: str = Field(..., title="List ID")


class ListItems(BaseModel):
    operation: Literal["list_items"] = _operation("list_items", "List Item", "List Items")
    site_id: str = Field(..., title="Site ID")
    list_id: str = Field(..., title="List ID")
    top: int = Field(100, ge=1, le=999, title="Maximum Results")


class GetItem(BaseModel):
    operation: Literal["get_item"] = _operation("get_item", "List Item", "Get Item")
    site_id: str = Field(..., title="Site ID")
    list_id: str = Field(..., title="List ID")
    item_id: str = Field(..., title="Item ID")


class CreateItem(BaseModel):
    operation: Literal["create_item"] = _operation("create_item", "List Item", "Create Item")
    site_id: str = Field(..., title="Site ID")
    list_id: str = Field(..., title="List ID")
    fields: Dict[str, Any] = Field(..., title="Column Values", description="JSON object of SharePoint column names and values", json_schema_extra={"ui:widget": "code_editor"})


class UpdateItem(BaseModel):
    operation: Literal["update_item"] = _operation("update_item", "List Item", "Update Item")
    site_id: str = Field(..., title="Site ID")
    list_id: str = Field(..., title="List ID")
    item_id: str = Field(..., title="Item ID")
    fields: Dict[str, Any] = Field(..., title="Column Values", description="JSON object of columns to update", json_schema_extra={"ui:widget": "code_editor"})


class DeleteItem(BaseModel):
    operation: Literal["delete_item"] = _operation("delete_item", "List Item", "Delete Item")
    site_id: str = Field(..., title="Site ID")
    list_id: str = Field(..., title="List ID")
    item_id: str = Field(..., title="Item ID")


class ListLibraries(BaseModel):
    operation: Literal["list_libraries"] = _operation("list_libraries", "Library", "List Document Libraries")
    site_id: str = Field(..., title="Site ID")


class ListFiles(BaseModel):
    operation: Literal["list_files"] = _operation("list_files", "Library", "List Files")
    drive_id: str = Field(..., title="Library Drive ID")
    folder_id: Optional[str] = Field(None, title="Folder ID", description="Leave blank for library root")


class GetFile(BaseModel):
    operation: Literal["get_file"] = _operation("get_file", "Library", "Get File Metadata")
    drive_id: str = Field(..., title="Library Drive ID")
    item_id: str = Field(..., title="File ID")


class UploadTextFile(BaseModel):
    operation: Literal["upload_text_file"] = _operation("upload_text_file", "Library", "Upload Text File")
    drive_id: str = Field(..., title="Library Drive ID")
    file_path: str = Field(..., title="File Path", description="Path relative to library root, including file name")
    content: str = Field(..., title="Text Content", json_schema_extra={"ui:widget": "code_editor"})


SharePointConfig = Annotated[
    Union[
        GetRootSite, SearchSites, GetSite, ListLists, GetList,
        ListItems, GetItem, CreateItem, UpdateItem, DeleteItem,
        ListLibraries, ListFiles, GetFile, UploadTextFile,
    ],
    Discriminator("operation"),
]


class SharePointNodeConfig(NodeConfig[SharePointConfig, SharePointOAuthCredential]):
    pass


class SharePointNode(WorkflowNode):
    """Manage SharePoint content with a user's delegated Microsoft grant."""

    integration_type = "automation-microsoft-sharepoint"
    scope_registry = SHAREPOINT_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_root_site", noun="site")
    edit_examples = [
        "Find the project site and list its documents",
        "Add a row to the team issue tracker list",
        "Update a SharePoint list item with the latest status",
        "Upload a meeting summary to a document library",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return SharePointNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="microsoft",
        )

    async def _token(self, credential: SharePointOAuthCredential) -> str:
        data = credential.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=data,
            refresh=refresh_access_token, provider="microsoft", caller_path="execute",
        )
        credential.access_token = data["access_token"]
        credential.refresh_token = data.get("refresh_token", credential.refresh_token)
        credential.expires_at = data.get("expires_at", credential.expires_at)
        return token

    @staticmethod
    async def _request(token: str, method: str, path: str, *, params=None, body=None, content=None) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"}
        if content is not None:
            headers["Content-Type"] = "text/plain; charset=utf-8"
        elif body is not None:
            headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method, f"{GRAPH}{path}", headers=headers, params=params,
                json=body, content=content,
            )
        if response.status_code >= 400:
            try:
                error = response.json().get("error", {})
                message = error.get("message") or response.reason_phrase
            except (ValueError, AttributeError):
                message = response.reason_phrase
            raise ValueError(f"SharePoint request failed ({response.status_code}): {message}")
        if not response.content:
            return {"success": True}
        return _without_download_urls(response.json())

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, SharePointNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Microsoft account to use SharePoint")
        c = self.config.config
        token = await self._token(self.config.credentials)
        start = time.monotonic()
        if isinstance(c, GetRootSite):
            result = await self._request(token, "GET", "/sites/root")
        elif isinstance(c, SearchSites):
            result = await self._request(token, "GET", "/sites", params={"search": c.query})
        elif isinstance(c, GetSite):
            result = await self._request(token, "GET", f"/sites/{_id(c.site_id)}")
        elif isinstance(c, ListLists):
            result = await self._request(token, "GET", f"/sites/{_id(c.site_id)}/lists")
        elif isinstance(c, GetList):
            result = await self._request(token, "GET", f"/sites/{_id(c.site_id)}/lists/{_id(c.list_id)}")
        elif isinstance(c, ListItems):
            result = await self._request(token, "GET", f"/sites/{_id(c.site_id)}/lists/{_id(c.list_id)}/items", params={"$expand": "fields", "$top": c.top})
        elif isinstance(c, GetItem):
            result = await self._request(token, "GET", f"/sites/{_id(c.site_id)}/lists/{_id(c.list_id)}/items/{_id(c.item_id)}", params={"$expand": "fields"})
        elif isinstance(c, CreateItem):
            result = await self._request(token, "POST", f"/sites/{_id(c.site_id)}/lists/{_id(c.list_id)}/items", body={"fields": c.fields})
        elif isinstance(c, UpdateItem):
            result = await self._request(token, "PATCH", f"/sites/{_id(c.site_id)}/lists/{_id(c.list_id)}/items/{_id(c.item_id)}/fields", body=c.fields)
        elif isinstance(c, DeleteItem):
            result = await self._request(token, "DELETE", f"/sites/{_id(c.site_id)}/lists/{_id(c.list_id)}/items/{_id(c.item_id)}")
        elif isinstance(c, ListLibraries):
            result = await self._request(token, "GET", f"/sites/{_id(c.site_id)}/drives")
        elif isinstance(c, ListFiles):
            folder = f"/items/{_id(c.folder_id)}" if c.folder_id else "/root"
            result = await self._request(token, "GET", f"/drives/{_id(c.drive_id)}{folder}/children")
        elif isinstance(c, GetFile):
            result = await self._request(token, "GET", f"/drives/{_id(c.drive_id)}/items/{_id(c.item_id)}")
        elif isinstance(c, UploadTextFile):
            data = c.content.encode("utf-8")
            if len(data) > 4 * 1024 * 1024:
                raise ValueError("Text file exceeds the 4 MB simple-upload limit")
            result = await self._request(token, "PUT", f"/drives/{_id(c.drive_id)}/root:/{_file_path(c.file_path)}:/content", content=data)
        else:
            raise ValueError(f"Unsupported SharePoint operation: {c.operation}")
        if isinstance(result, dict):
            result.setdefault("execution_time_ms", round((time.monotonic() - start) * 1000))
        return result
