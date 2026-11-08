"""Zoho WorkDrive v1 file and collaboration operations.

Pinned provider contract: zoho/zohoworkdrive-oas at e372b16eaabf43d755884cababfb867f64a0be9c.
Every action uses one fixed documented endpoint; provider JSON and pagination
metadata are preserved. Lists return one page and never follow response URLs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.zoho_work_drive_oauth import ACCOUNTS_ORIGINS, OAUTH_PROVIDER, validate_api_domain
from nodes.scopes.zoho_work_drive import ZOHO_WORK_DRIVE_SCOPES
from utils.ssrf import guarded_async_client

MEDIA = "application/vnd.api+json"


class ZohoWorkDriveOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Zoho WorkDrive OAuth", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth", "x-oauth-provider": "zoho_work_drive",
            "x-oauth-scopes": sorted(ZOHO_WORK_DRIVE_SCOPES.declared_scopes()),
            "x-credential-url": "https://api-console.zoho.com/",
        })
    credential_type: Literal["zoho_work_drive_oauth"] = Field("zoho_work_drive_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str
    accounts_server: str
    api_domain: str
    _api_origin = field_validator("api_domain")(validate_api_domain)

    @field_validator("accounts_server")
    @classmethod
    def accounts_origin(cls, value):
        if value not in ACCOUNTS_ORIGINS:
            raise ValueError("Use a documented Zoho accounts origin")
        return value


def _id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,255}", value):
        raise ValueError("Use a single Zoho WorkDrive resource ID")
    return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name.endswith("_id") or info.field_name == "zuid":
            return _id(value)
        return value


def identifier(title):
    return (str, Field(..., min_length=1, max_length=256, title=title,
        description="Copy the resource ID from WorkDrive or a preceding read operation."))


RESOURCE = {"resource_id": identifier("File or folder ID")}
TEAM = {"team_id": identifier("Team ID")}
COMMENT = {"comment_id": identifier("Comment ID")}
LINK = {"link_id": identifier("Share link ID")}
NAME = (str, Field(..., min_length=1, max_length=200, title="Name"))
TEXT = (str, Field(..., min_length=1, max_length=100000, title="Comment HTML"))
PAGE = {
    "limit": (int, Field(50, ge=1, le=50, title="Page size")),
    "offset": (int, Field(0, ge=0, title="Offset", description="Start index for this page. Advance by the page size to read the next page.")),
}


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    label: str
    fields: dict[str, tuple[Any, Any]]
    category: str
    body_type: str | None = None


OPS = {
    "get_user": Operation("GET", "/users/me", "Get Current User", {}, "Account"),
    "list_teams": Operation("GET", "/users/{zuid}/teams", "List User Teams", {"zuid": identifier("Zoho user ID")}, "Account"),
    "get_team": Operation("GET", "/teams/{team_id}", "Get Team", TEAM, "Teams"),
    "list_team_folders": Operation("GET", "/teams/{team_id}/teamfolders", "List Team Folders", {**TEAM, **PAGE}, "Teams"),
    "get_team_folder": Operation("GET", "/teamfolders/{teamfolder_id}", "Get Team Folder", {"teamfolder_id": identifier("Team folder ID")}, "Teams"),
    "list_files": Operation("GET", "/files/{folder_id}/files", "List Folder Contents", {"folder_id": identifier("Folder ID"), **PAGE}, "Files"),
    "get_file": Operation("GET", "/files/{resource_id}", "Get File or Folder", RESOURCE, "Files"),
    "create_folder": Operation("POST", "/files", "Create Folder", {"parent_id": identifier("Parent folder ID"), "name": NAME}, "Files", "files"),
    "rename_file": Operation("PATCH", "/files/{resource_id}", "Rename File or Folder", {**RESOURCE, "name": NAME}, "Files", "files"),
    "move_file": Operation("PATCH", "/files/{resource_id}", "Move File or Folder", {**RESOURCE, "parent_id": identifier("Destination folder ID")}, "Files", "files"),
    "trash_file": Operation("PATCH", "/files/{resource_id}", "Move File or Folder to Trash", RESOURCE, "Files", "files"),
    "restore_file": Operation("PATCH", "/files/{resource_id}", "Restore File or Folder", RESOURCE, "Files", "files"),
    "copy_file": Operation("POST", "/files/{destination_id}/copy", "Copy File or Folder", {"destination_id": identifier("Destination folder ID"), "source_id": identifier("Source file or folder ID")}, "Files", "files"),
    "list_versions": Operation("GET", "/files/{resource_id}/versions", "List File Versions", RESOURCE, "Files"),
    "list_comments": Operation("GET", "/files/{resource_id}/comments", "List File Comments", RESOURCE, "Comments"),
    "get_comment": Operation("GET", "/comments/{comment_id}", "Get Comment", COMMENT, "Comments"),
    "create_comment": Operation("POST", "/comments", "Create Comment", {**RESOURCE, "comment_html": TEXT}, "Comments", "comments"),
    "edit_comment": Operation("PATCH", "/comments/{comment_id}", "Edit Comment", {**COMMENT, "comment_html": TEXT}, "Comments", "comments"),
    "delete_comment": Operation("DELETE", "/comments/{comment_id}", "Delete Comment", COMMENT, "Comments"),
    "list_links": Operation("GET", "/files/{resource_id}/links", "List External Share Links", RESOURCE, "Sharing"),
    "get_link": Operation("GET", "/links/{link_id}", "Get External Share Link", LINK, "Sharing"),
    "revoke_link": Operation("DELETE", "/links/{link_id}", "Revoke External Share Link", LINK, "Sharing"),
    "search_files": Operation("GET", "/teams/{team_id}/records", "Search Files and Folders", {**TEAM, "query": (str, Field(..., min_length=1, max_length=2000, title="Search query")), **PAGE}, "Files"),
}

OP_MODELS = {
    name: create_model("ZohoWorkDrive" + "".join(word.title() for word in name.split("_")) + "Config",
        __base__=_Input,
        operation=(Literal[name], Field(name, title=spec.label, json_schema_extra={
            "ui:hidden": True, "x-operation-category": spec.category,
            "x-operation-kind": "read" if spec.method == "GET" else "write",
        })), **spec.fields)
    for name, spec in OPS.items()
}
OperationConfig = Annotated[Union[tuple(OP_MODELS.values())], Field(discriminator="operation")]


class ZohoWorkDriveConfig(NodeConfig[OperationConfig, ZohoWorkDriveOAuthCredential]):
    pass


async def workdrive_request(credential, method, path, *, params=None, body=None):
    origin = validate_api_domain(credential["api_domain"])
    async with guarded_async_client(timeout=30, follow_redirects=False) as client:
        response = await client.request(method, origin + "/workdrive/api/v1" + path,
            headers={"Authorization": "Bearer " + credential["access_token"],
                "Accept": MEDIA, **({"Content-Type": MEDIA} if body is not None else {})},
            params=params, json=body)
    if not 200 <= response.status_code < 300:
        try:
            errors = response.json().get("errors", [])
            titles = [error["title"] for error in errors if isinstance(error, dict) and isinstance(error.get("title"), str)]
        except (ValueError, AttributeError, TypeError):
            titles = []
        message = "; ".join(titles) or f"Zoho WorkDrive returned HTTP {response.status_code}"
        # Preserve the provider's rejection while excluding token echoes.
        for key in ("access_token", "refresh_token"):
            if credential.get(key): message = message.replace(credential[key], "[redacted]")
        raise ValueError(message)
    if response.status_code == 204 or (method == "DELETE" and not response.content):
        return {"status": "success", "http_status": response.status_code}
    try:
        data = response.json()
    except ValueError:
        raise ValueError("Zoho WorkDrive returned an unexpected non-JSON response") from None
    if not isinstance(data, (dict, list)):
        raise ValueError("Zoho WorkDrive returned an unexpected response shape")
    if isinstance(data, dict) and data.get("errors"):
        errors = data["errors"] if isinstance(data["errors"], list) else []
        message = "; ".join(str(e.get("title", "Zoho WorkDrive error")) for e in errors if isinstance(e, dict)) or "Zoho WorkDrive returned an error"
        for key in ("access_token", "refresh_token"):
            if credential.get(key): message = message.replace(credential[key], "[redacted]")
        raise ValueError(message)
    return {"status": "success", "http_status": response.status_code, "data": data}


class ZohoWorkDriveNode(WorkflowNode):
    integration_type = "automation-zoho-work-drive"
    scope_registry = ZOHO_WORK_DRIVE_SCOPES
    connection_evidence = ConnectionEvidence(identity_operation="get_user", noun="account")
    edit_examples = ["Create a folder in Zoho WorkDrive", "Search Zoho WorkDrive files", "Add a comment to a WorkDrive file"]

    @classmethod
    def get_config_model(cls):
        return ZohoWorkDriveConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=OAUTH_PROVIDER.bind_refresh(credential_data),
            additional_token_fields=OAUTH_PROVIDER.credential_fields, provider="zoho_work_drive")

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Zoho WorkDrive account")
        credential = self.config.credentials.model_dump()
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=credential,
            refresh=OAUTH_PROVIDER.bind_refresh(credential),
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
            provider="zoho_work_drive", caller_path="execute")
        operation = self.config.config
        spec = OPS[operation.operation]
        values = operation.model_dump(exclude_none=True)
        path = spec.path
        path_keys = re.findall(r"\{([^}]+)\}", path)
        for key in path_keys:
            path = path.replace("{" + key + "}", quote(_id(values[key]), safe=""))
        params = {}
        if "limit" in values:
            params = {"page[limit]": str(values["limit"]), "page[offset]": str(values["offset"])}
        if operation.operation == "search_files":
            params["search[all]"] = values["query"]
        body = None
        if spec.body_type:
            attributes = {key: value for key, value in values.items() if key not in {"operation", *path_keys}}
            if operation.operation == "copy_file":
                attributes = {"resource_id": attributes["source_id"]}
            elif operation.operation in ("trash_file", "restore_file"):
                attributes = {"status": 51 if operation.operation == "trash_file" else 1}
            body = {"data": {"type": spec.body_type, "attributes": attributes}}
        result = await workdrive_request(credential, spec.method, path, params=params or None, body=body)
        return {"action": operation.operation, **result}
