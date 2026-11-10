"""Automate PowerPoint files stored in OneDrive or SharePoint with Graph v1.0.

Each action issues one documented drive-item request. Graph exposes presentation
file management here; slide content editing requires a different Office API.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.onedrive_node import OneDriveOAuthCredential
from nodes.scopes.microsoft_powerpoint import POWERPOINT_SCOPES

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
ITEM = "/drives/{drive_id}/items/{presentation_id}"


@dataclass(frozen=True)
class Operation:
    title: str
    method: str
    path: str
    fields: tuple[str, ...] = ()
    body: str = ""
    collection: bool = False
    description: str = ""


OPERATIONS = {
    "get_account": Operation("Get Microsoft Account", "GET", "/me"),
    "get_my_drive": Operation("Get My Presentation Drive", "GET", "/me/drive"),
    "get_root_folder": Operation("Get Drive Root Folder", "GET", "/drives/{drive_id}/root", ("drive_id",)),
    "list_presentations": Operation("List Presentations in Folder", "GET", "/drives/{drive_id}/items/{folder_id}/children", ("drive_id", "folder_id", "top"), collection=True,
        description="List one page of folder children and return PowerPoint files (.pptx, .ppt, .ppsx, .pps, .potx, .pot, .pptm, .ppsm, .potm). The limit applies before filtering; next_link refers to the unfiltered Graph page."),
    "get_presentation": Operation("Get Presentation Metadata", "GET", ITEM, ("drive_id", "presentation_id")),
    "rename_presentation": Operation("Rename Presentation", "PATCH", ITEM, ("drive_id", "presentation_id", "name"), "rename"),
    "move_presentation": Operation("Move Presentation", "PATCH", ITEM, ("drive_id", "presentation_id", "folder_id"), "move", description="Move a presentation to another folder in the same drive. Use the destination folder ID, including the root folder's actual ID."),
    "copy_presentation": Operation("Copy Presentation from Template", "POST", ITEM + "/copy", ("drive_id", "presentation_id", "folder_id", "name"), "copy", description="Start an asynchronous copy in the same drive. A 202 response means accepted; monitor_url tracks completion."),
    "delete_presentation": Operation("Delete Presentation", "DELETE", ITEM, ("drive_id", "presentation_id"), description="Move the presentation to the recycle bin."),
    "preview_presentation": Operation("Get Presentation Preview", "POST", ITEM + "/preview", ("drive_id", "presentation_id"), "preview", description="Return a temporary preview for the caller's own use. Available for OneDrive for Business and SharePoint only."),
    "create_share_link": Operation("Create Presentation Sharing Link", "POST", ITEM + "/createLink", ("drive_id", "presentation_id", "link_type", "link_scope"), "link", description="Create or reuse a view/edit sharing link. Tenant sharing policy determines which scopes are allowed."),
    "list_permissions": Operation("List Presentation Permissions", "GET", ITEM + "/permissions", ("drive_id", "presentation_id"), collection=True),
    "get_permission": Operation("Get Presentation Permission", "GET", ITEM + "/permissions/{permission_id}", ("drive_id", "presentation_id", "permission_id")),
    "update_permission": Operation("Change Presentation Permission Role", "PATCH", ITEM + "/permissions/{permission_id}", ("drive_id", "presentation_id", "permission_id", "role"), "role", description="Change a direct sharing permission's role. Inherited permissions cannot be changed here."),
    "delete_permission": Operation("Remove Presentation Permission", "DELETE", ITEM + "/permissions/{permission_id}", ("drive_id", "presentation_id", "permission_id"), description="Remove a direct sharing permission; inherited permissions must be changed on the ancestor."),
    "list_versions": Operation("List Presentation Versions", "GET", ITEM + "/versions", ("drive_id", "presentation_id"), collection=True),
    "get_version": Operation("Get Presentation Version", "GET", ITEM + "/versions/{version_id}", ("drive_id", "presentation_id", "version_id")),
    "restore_version": Operation("Restore Presentation Version", "POST", ITEM + "/versions/{version_id}/restoreVersion", ("drive_id", "presentation_id", "version_id"), description="Create a new current version from a previous version, preserving version history."),
    "list_thumbnails": Operation("List Presentation Thumbnails", "GET", ITEM + "/thumbnails", ("drive_id", "presentation_id"), collection=True),
}


def _config_model(key: str, op: Operation) -> type[BaseModel]:
    fields: dict[str, Any] = {
        "operation": (Literal[key], Field(key, title=op.title, json_schema_extra={
            "ui:hidden": True, "const": key, "x-display-name": op.title,
            "x-category": "PowerPoint", "x-is-trigger": False,
        })),
    }
    for field in op.fields:
        if field == "top":
            fields[field] = (int, Field(100, ge=1, le=200, title="Page size"))
        elif field == "link_type":
            fields[field] = (Literal["view", "edit"], Field("view", title="Link access"))
        elif field == "link_scope":
            fields[field] = (Literal["organization", "anonymous"], Field("organization", title="Link audience", description="Organization links require a work/school account. Anonymous links require tenant policy to allow them."))
        elif field == "role":
            fields[field] = (Literal["read", "write"], Field("read", title="Permission role"))
        elif field == "name":
            fields[field] = (str, Field(..., min_length=1, max_length=255, pattern=r'^[^/\\:*?"<>|\x00-\x1f]+\.(?i:pptx|ppt|ppsx|pps|potx|pot|pptm|ppsm|potm)$', title="Presentation filename", description="Include the PowerPoint extension, such as Quarterly Review.pptx."))
        else:
            descriptions = {
                "drive_id": "Drive ID from Get My Presentation Drive or the file's parentReference.driveId.",
                "presentation_id": "PowerPoint file's driveItem ID from List Presentations in Folder.",
                "folder_id": "Folder driveItem ID; Get Drive Root Folder returns the root folder's actual ID.",
                "permission_id": "Permission ID from List Presentation Permissions.",
                "version_id": "Version ID from List Presentation Versions.",
            }
            fields[field] = (str, Field(..., min_length=1, max_length=1024, pattern=r"^[^\x00-\x1f]+$", title=field.replace("_", " ").title(), description=descriptions[field]))
    return create_model("PowerPoint" + "".join(p.title() for p in key.split("_")) + "Config",
        __config__=ConfigDict(extra="forbid", title=op.title), __doc__=op.description or op.title, **fields)


CONFIG_MODELS = {key: _config_model(key, op) for key, op in OPERATIONS.items()}
PowerPointOperationConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class PowerPointNodeConfig(NodeConfig[PowerPointOperationConfig, OneDriveOAuthCredential]):
    """Reuse the Microsoft drive credential the staging sign-in actually issues."""


class MicrosoftPowerPointNode(WorkflowNode):
    integration_type = "automation-microsoft-powerpoint"
    borrowed_credential_types = frozenset({"microsoft_onedrive_oauth"})
    credential_provider_labels = {"microsoft": "Microsoft Account"}
    scope_registry = POWERPOINT_SCOPES
    connection_evidence = ConnectionEvidence(identity_operation="get_account", noun="Microsoft account", identity_keys=("displayName", "mail", "userPrincipalName", "id"))
    edit_examples = ["Copy a PowerPoint template for each new project", "Share a presentation with a view link", "Restore a previous version of a slide deck"]

    @classmethod
    def get_config_model(cls):
        return PowerPointNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.microsoft_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="microsoft")

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.microsoft_oauth import refresh_access_token

        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your Microsoft account to manage PowerPoint files")
        credential_data = credential.model_dump()
        token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=credential_data, refresh=refresh_access_token,
            provider="microsoft", caller_path="execute")
        for key in ("access_token", "refresh_token", "expires_at"):
            if key in credential_data:
                setattr(credential, key, credential_data[key])

        op = OPERATIONS[config.operation]
        values = config.model_dump(exclude={"operation"})
        path = op.path
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        kwargs: dict[str, Any] = {"headers": {"Authorization": f"Bearer {token}", "Accept": "application/json"}}
        if "top" in values:
            kwargs["params"] = {"$top": values["top"]}
        if op.body == "rename":
            kwargs["json"] = {"name": values["name"]}
        elif op.body == "move":
            kwargs["json"] = {"parentReference": {"id": values["folder_id"]}}
        elif op.body == "copy":
            kwargs["json"] = {"name": values["name"], "parentReference": {"driveId": values["drive_id"], "id": values["folder_id"]}}
        elif op.body == "preview":
            kwargs["json"] = {}
        elif op.body == "link":
            kwargs["json"] = {"type": values["link_type"], "scope": values["link_scope"]}
        elif op.body == "role":
            kwargs["json"] = {"roles": [values["role"]]}

        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(op.method, GRAPH_ROOT + path, **kwargs)
        if response.is_error:
            try:
                error = response.json().get("error", {})
                message = error.get("message") if isinstance(error, dict) else str(error)
            except (ValueError, AttributeError):
                message = response.text[:500]
            raise ValueError(f"Microsoft Graph ({response.status_code}): {message or response.reason_phrase}")
        if response.is_redirect:
            raise ValueError(f"Unexpected Microsoft Graph redirect ({response.status_code})")

        result: dict[str, Any] = {"status": "success", "operation": config.operation}
        if config.operation == "copy_presentation" and response.status_code == 202:
            return {**result, "status": "accepted", "monitor_url": response.headers.get("Location")}
        if not response.content:
            return result
        data = response.json()
        if op.collection:
            if not isinstance(data, dict) or not isinstance(data.get("value"), list):
                raise ValueError("Microsoft Graph returned an invalid collection")
            items = data["value"]
            if config.operation == "list_presentations":
                items = [item for item in items if isinstance(item, dict) and item.get("file") is not None
                    and str(item.get("name", "")).lower().endswith((".pptx", ".ppt", ".ppsx", ".pps", ".potx", ".pot", ".pptm", ".ppsm", ".potm"))]
            result.update(items=items, count=len(items), next_link=data.get("@odata.nextLink"))
        elif not isinstance(data, dict):
            raise ValueError("Microsoft Graph returned an invalid resource")
        else:
            result["data"] = data
        return result
