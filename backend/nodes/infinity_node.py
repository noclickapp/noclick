"""Infinity API v2 operations pinned to the provider's Morava contract.

Documentation: https://devdocs.startinfinity.com/2026-04-20.morava/
Lists return exactly one page; callers pass the returned cursors explicitly.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.startinfinity.com/api/v2"
VERSION = "2026-04-20.morava"


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Paste a single Infinity resource ID")
    return value


def _json_array(value):
    try:
        data = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError):
        raise ValueError("Enter a valid JSON array") from None
    if not isinstance(data, list) or len(data) > 1000:
        raise ValueError("Enter a JSON array of at most 1000 entries")
    return data


class InfinityAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Infinity API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.startinfinity.com/profile/developer/tokens",
            "x-credential-instructions": "Enable developer features in Infinity profile settings, open Developer > Tokens, and create a token. Paste the token here without the Bearer prefix. Your token must have access to the workspaces and boards you automate.",
        })
    credential_type: Literal["infinity_api_token"] = Field("infinity_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", repr=False, min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the token without a header or spaces")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if value is not None and info.field_name.endswith("_id"):
            return _id(value)
        return value


class _Page(_Input):
    limit: int = Field(100, ge=1, le=100, description="Maximum records in this page.")
    after: str | None = Field(None, max_length=4096, description="The after cursor from the preceding page.")
    before: str | None = Field(None, max_length=4096, description="The before cursor for paging backwards.")
    sort_by: Literal["id", "created_at"] = "created_at"
    sort_direction: Literal["asc", "desc"] = "desc"

    @model_validator(mode="after")
    def cursors(self):
        if self.after is not None and self.before is not None:
            raise ValueError("Use either after or before, not both")
        return self


class _ItemWrite(_Input):
    folder_id: str | None = None
    parent_id: str | None = None
    values_json: str | None = Field(None, max_length=200000, title="Attribute values (JSON)",
        description='Array of {"attribute_id": "...", "data": ...}. Use the board attribute IDs and the data shape for each attribute type. Omitted values are not sent.',
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("values_json")
    @classmethod
    def values(cls, value):
        if value is None:
            return value
        for entry in _json_array(value):
            if not isinstance(entry, dict) or set(entry) != {"attribute_id", "data"}:
                raise ValueError("Each value needs only attribute_id and data")
            _id(entry["attribute_id"])
            data = entry["data"]
            if not isinstance(data, (bool, str, dict, list)):
                raise ValueError("Attribute data must be a boolean, string, object or array")
            if isinstance(data, list) and any(not isinstance(x, (str, dict)) for x in data):
                raise ValueError("Array attribute data must contain strings or objects")
        return value


class _FolderWrite(_Input):
    name: str = Field(..., min_length=1, max_length=1000)
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    parent_id: str | None = Field(None, description="Parent folder or board ID; omit for a top level folder.")
    sort_order: str | None = Field(None, max_length=100)
    attribute_ids_json: str | None = Field(None, max_length=200000, title="Attribute IDs (JSON)",
        description="JSON array of attribute IDs used in the folder; omitted leaves them unchanged.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("attribute_ids_json")
    @classmethod
    def attributes(cls, value):
        if value is not None:
            for entry in _json_array(value):
                _id(entry)
        return value


class InfinityGetProfileConfig(_Input):
    """Get my profile data."""
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"ui:hidden": True})


class InfinityListWorkspacesConfig(_Page):
    """List workspaces."""
    operation: Literal["list_workspaces"] = Field("list_workspaces", json_schema_extra={"ui:hidden": True})


class InfinityListBoardsConfig(_Page):
    """List boards."""
    operation: Literal["list_boards"] = Field("list_boards", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")


class InfinityCreateBoardConfig(_Input):
    """Create board."""
    operation: Literal["create_board"] = Field("create_board", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    name: str = Field(..., min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=10000)
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    user_ids_json: str | None = Field(None, max_length=20000, title="Member IDs (JSON)",
        description="JSON array of workspace member IDs. Infinity adds the current user automatically.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("user_ids_json")
    @classmethod
    def members(cls, value):
        if value is not None and any(type(x) is not int or x <= 0 for x in _json_array(value)):
            raise ValueError("Member IDs must be positive integers")
        return value


class InfinityGetBoardConfig(_Input):
    """Get board."""
    operation: Literal["get_board"] = Field("get_board", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")


class InfinityListAttributesConfig(_Page):
    """List attributes."""
    operation: Literal["list_attributes"] = Field("list_attributes", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")


class InfinityGetAttributeConfig(_Input):
    """Get attribute."""
    operation: Literal["get_attribute"] = Field("get_attribute", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")
    attribute_id: str = Field(..., title="Attribute ID")


class InfinityListItemsConfig(_Page):
    """List items."""
    operation: Literal["list_items"] = Field("list_items", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")
    folder_id: str | None = Field(None, description="Filter items to this folder.")


class InfinityCreateItemConfig(_ItemWrite):
    """Create item."""
    operation: Literal["create_item"] = Field("create_item", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")
    folder_id: str = Field(..., title="Folder ID")


class InfinityGetItemConfig(_Input):
    """Get item."""
    operation: Literal["get_item"] = Field("get_item", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")
    item_id: str = Field(..., title="Item ID")


class InfinityUpdateItemConfig(_ItemWrite):
    """Update item."""
    operation: Literal["update_item"] = Field("update_item", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")
    item_id: str = Field(..., title="Item ID")

    @model_validator(mode="after")
    def changes(self):
        if self.folder_id is None and self.parent_id is None and self.values_json is None:
            raise ValueError("Provide attribute values, a folder or a parent to update")
        return self


class InfinityDeleteItemConfig(_Input):
    """Delete item."""
    operation: Literal["delete_item"] = Field("delete_item", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")
    item_id: str = Field(..., title="Item ID")


class InfinityListCommentsConfig(_Page):
    """List comments."""
    operation: Literal["list_comments"] = Field("list_comments", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")
    item_id: str = Field(..., title="Item ID")


class InfinityCreateCommentConfig(_Input):
    """Create comment."""
    operation: Literal["create_comment"] = Field("create_comment", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")
    item_id: str = Field(..., title="Item ID")
    text: str = Field(..., min_length=1, max_length=100000, description="Comment body; Infinity accepts HTML.")
    parent_id: str | None = Field(None, description="Parent comment ID for a reply.")


class InfinityGetCommentConfig(_Input):
    """Get comment."""
    operation: Literal["get_comment"] = Field("get_comment", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")
    item_id: str = Field(..., title="Item ID")
    comment_id: str = Field(..., title="Comment ID")


class InfinityUpdateCommentConfig(_Input):
    """Update comment."""
    operation: Literal["update_comment"] = Field("update_comment", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")
    item_id: str = Field(..., title="Item ID")
    comment_id: str = Field(..., title="Comment ID")
    text: str = Field(..., min_length=1, max_length=100000, description="Comment body; Infinity accepts HTML.")


class InfinityDeleteCommentConfig(_Input):
    """Delete comment."""
    operation: Literal["delete_comment"] = Field("delete_comment", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")
    item_id: str = Field(..., title="Item ID")
    comment_id: str = Field(..., title="Comment ID")


class InfinityListFoldersConfig(_Page):
    """List folders."""
    operation: Literal["list_folders"] = Field("list_folders", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")


class InfinityCreateFolderConfig(_FolderWrite):
    """Create folder."""
    operation: Literal["create_folder"] = Field("create_folder", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")


class InfinityGetFolderConfig(_Input):
    """Get folder."""
    operation: Literal["get_folder"] = Field("get_folder", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")
    folder_id: str = Field(..., title="Folder ID")


class InfinityUpdateFolderConfig(_FolderWrite):
    """Update folder."""
    operation: Literal["update_folder"] = Field("update_folder", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")
    folder_id: str = Field(..., title="Folder ID")


class InfinityDeleteFolderConfig(_Input):
    """Delete folder."""
    operation: Literal["delete_folder"] = Field("delete_folder", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")
    board_id: str = Field(..., title="Board ID")
    folder_id: str = Field(..., title="Folder ID")


class InfinityListMembersConfig(_Page):
    """List members."""
    operation: Literal["list_members"] = Field("list_members", json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., title="Workspace ID")


InfinityConfig = Annotated[Union[
    InfinityGetProfileConfig,
    InfinityListWorkspacesConfig,
    InfinityListBoardsConfig,
    InfinityCreateBoardConfig,
    InfinityGetBoardConfig,
    InfinityListAttributesConfig,
    InfinityGetAttributeConfig,
    InfinityListItemsConfig,
    InfinityCreateItemConfig,
    InfinityGetItemConfig,
    InfinityUpdateItemConfig,
    InfinityDeleteItemConfig,
    InfinityListCommentsConfig,
    InfinityCreateCommentConfig,
    InfinityGetCommentConfig,
    InfinityUpdateCommentConfig,
    InfinityDeleteCommentConfig,
    InfinityListFoldersConfig,
    InfinityCreateFolderConfig,
    InfinityGetFolderConfig,
    InfinityUpdateFolderConfig,
    InfinityDeleteFolderConfig,
    InfinityListMembersConfig
], Field(discriminator="operation")]


class InfinityFullConfig(NodeConfig[InfinityConfig, InfinityAPITokenCredential]):
    pass


ROUTES = {
    "get_profile": ("GET", "/profile"),
    "list_workspaces": ("GET", "/workspaces"),
    "list_boards": ("GET", "/workspaces/{workspace}/boards"),
    "create_board": ("POST", "/workspaces/{workspace}/boards"),
    "get_board": ("GET", "/workspaces/{workspace}/boards/{board}"),
    "list_attributes": ("GET", "/workspaces/{workspace}/boards/{board}/attributes"),
    "get_attribute": ("GET", "/workspaces/{workspace}/boards/{board}/attributes/{attribute}"),
    "list_items": ("GET", "/workspaces/{workspace}/boards/{board}/items"),
    "create_item": ("POST", "/workspaces/{workspace}/boards/{board}/items"),
    "get_item": ("GET", "/workspaces/{workspace}/boards/{board}/items/{item}"),
    "update_item": ("PUT", "/workspaces/{workspace}/boards/{board}/items/{item}"),
    "delete_item": ("DELETE", "/workspaces/{workspace}/boards/{board}/items/{item}"),
    "list_comments": ("GET", "/workspaces/{workspace}/boards/{board}/items/{item}/comments"),
    "create_comment": ("POST", "/workspaces/{workspace}/boards/{board}/items/{item}/comments"),
    "get_comment": ("GET", "/workspaces/{workspace}/boards/{board}/items/{item}/comments/{comment}"),
    "update_comment": ("PUT", "/workspaces/{workspace}/boards/{board}/items/{item}/comments/{comment}"),
    "delete_comment": ("DELETE", "/workspaces/{workspace}/boards/{board}/items/{item}/comments/{comment}"),
    "list_folders": ("GET", "/workspaces/{workspace}/boards/{board}/folders"),
    "create_folder": ("POST", "/workspaces/{workspace}/boards/{board}/folders"),
    "get_folder": ("GET", "/workspaces/{workspace}/boards/{board}/folders/{folder}"),
    "update_folder": ("PUT", "/workspaces/{workspace}/boards/{board}/folders/{folder}"),
    "delete_folder": ("DELETE", "/workspaces/{workspace}/boards/{board}/folders/{folder}"),
    "list_members": ("GET", "/workspaces/{workspace}/members"),
}


class InfinityNode(WorkflowNode):
    integration_type = "automation-infinity"
    connection_evidence = ConnectionEvidence(noun="workspaces", operation="list_workspaces", identity_operation="get_profile")

    @classmethod
    def get_config_model(cls):
        return InfinityFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Infinity API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        for field in re.findall(r"\{(\w+)\}", path):
            path = path.replace("{" + field + "}", quote(_id(values.pop(field + "_id")), safe=""))
        query = {}
        body = None
        if method == "GET":
            for key in ("limit", "after", "before", "sort_by", "sort_direction", "folder_id"):
                if key in values:
                    query[key] = values[key]
        elif method in {"POST", "PUT"}:
            body = {}
            for key in ("name", "description", "color", "text", "folder_id", "parent_id", "sort_order"):
                if key in values:
                    body[key] = values[key]
            for key in ("values", "attribute_ids", "user_ids"):
                if key + "_json" in values:
                    body[key] = _json_array(values[key + "_json"])
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=query,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json", "X-API-Version": VERSION},
                    **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            return {"status": "error", "error": "Infinity request could not be completed"}
        status = response.status_code
        if status != (201 if method == "POST" else 200):
            message = f"Infinity returned HTTP {status}"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:2000]
            except ValueError:
                pass
            return {"status": "error", "http_status": status, "error": message.replace(token, "[redacted]")}
        if len(response.content) > 5_000_000:
            raise ValueError("Infinity response exceeds the supported size")
        if response.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise ValueError("Expected JSON from Infinity")
        result = response.json()
        if not isinstance(result, dict) or "error" in result or "errors" in result:
            raise ValueError("Infinity returned an unexpected response")
        if op.operation.startswith("list_"):
            if not isinstance(result.get("data"), list) or type(result.get("has_more")) is not bool:
                raise ValueError("Infinity returned an invalid page")
            if result["has_more"] and not (result.get("after") or result.get("before")):
                raise ValueError("Infinity returned more records without a cursor")
            if any(not isinstance(x, dict) for x in result["data"]):
                raise ValueError("Infinity returned invalid records")
            output = {"data": result["data"], "has_more": result["has_more"],
                "after": result.get("after"), "before": result.get("before")}
        else:
            if not isinstance(result.get("id"), (str, int)) or isinstance(result.get("id"), bool):
                raise ValueError("Infinity returned a resource without an ID")
            output = {"data": result}
        # A provider response must never echo the saved bearer token.
        def redact(value):
            if isinstance(value, str):
                return value.replace(token, "[redacted]")
            if isinstance(value, list):
                return [redact(x) for x in value]
            if isinstance(value, dict):
                return {k.replace(token, "[redacted]"): redact(v) for k, v in value.items()}
            return value
        return {"status": "success", "http_status": status, **redact(output)}
