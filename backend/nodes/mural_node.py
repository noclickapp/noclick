"""Mural public API workflow node.

The operation table follows Mural's public v1 reference. It keeps request paths,
fields, and response names together so the schema shown in FlowCanvas is the
same contract used by execution. The public API currently has no event webhook.
https://developers.mural.co/public/reference/intro
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.dynamic_options import require_credential_token
from nodes.scopes.mural import MURAL_SCOPES as MURAL_SCOPE_REGISTRY

logger = logging.getLogger(__name__)
MURAL_API_BASE = "https://app.mural.co/api/public/v1"
MURAL_SCOPES = sorted(MURAL_SCOPE_REGISTRY.declared_scopes())


class MuralOAuthCredential(BaseModel):
    """Mural authorization-code credential. Access tokens last 15 minutes."""

    credential_type: Literal["mural_oauth"] = Field("mural_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., title="Refresh Token", json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    name: Optional[str] = Field(None, title="User Name")
    email: Optional[str] = Field(None, title="Account Email")

    model_config = ConfigDict(title="Mural Account", json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "mural",
        "x-oauth-scopes": MURAL_SCOPES,
        "x-credential-url": "https://app.mural.co/me/apps",
    })


@dataclass(frozen=True)
class _Field:
    type: Any = str
    required: bool = True
    description: str = ""
    dynamic: Optional[str] = None
    depends_on: Optional[str] = None
    widget: Optional[str] = None


@dataclass(frozen=True)
class _Operation:
    category: str
    method: str
    path: str
    result: str
    fields: Dict[str, _Field]
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    read_only: bool = True


def _f(description: str = "", *, required: bool = True, dynamic: Optional[str] = None,
       depends_on: Optional[str] = None, widget: Optional[str] = None,
       type: Any = str) -> _Field:
    return _Field(type, required, description, dynamic, depends_on, widget)


_WORKSPACE = _f("Mural workspace ID", dynamic="workspace_id")
_ROOM = _f("Mural room ID", dynamic="room_id", depends_on="workspace_id", type=int)
_MURAL = _f("Mural ID", dynamic="mural_id", depends_on="room_id")
_LIMIT = _f("Maximum results per page", required=False, type=int)
_NEXT = _f("Pagination token from a previous result", required=False)

# Paths and request shapes verified against Mural's public API reference.
# All list operations expose Mural's `next` cursor instead of silently truncating.
OPERATIONS: Dict[str, _Operation] = {
    "get_me": _Operation("Users", "GET", "/users/me", "user", {}),
    "list_workspaces": _Operation("Workspaces", "GET", "/workspaces", "workspaces",
                                  {"limit": _LIMIT, "next": _NEXT}, query=("limit", "next")),
    "list_rooms": _Operation("Rooms", "GET", "/workspaces/{workspace_id}/rooms", "rooms",
                             {"workspace_id": _WORKSPACE, "limit": _LIMIT, "next": _NEXT}, query=("limit", "next")),
    "get_room": _Operation("Rooms", "GET", "/rooms/{room_id}", "room", {"room_id": _ROOM}),
    "create_room": _Operation("Rooms", "POST", "/rooms", "room", {
        "workspace_id": _WORKSPACE, "name": _f("Room name"),
        "type": _f("open or private room"), "description": _f("Room description", required=False),
    }, body=("workspace_id", "name", "type", "description"), read_only=False),
    "update_room": _Operation("Rooms", "PATCH", "/rooms/{room_id}", "room", {
        "room_id": _ROOM, "name": _f("New room name", required=False),
        "description": _f("New description", required=False),
        "type": _f("open or private", required=False),
    }, body=("name", "description", "type"), read_only=False),
    "delete_room": _Operation("Rooms", "DELETE", "/rooms/{room_id}", "deleted", {"room_id": _ROOM}, read_only=False),
    "list_folders": _Operation("Rooms", "GET", "/rooms/{room_id}/folders", "folders", {
        "room_id": _ROOM, "limit": _LIMIT, "next": _NEXT,
    }, query=("limit", "next")),
    "create_folder": _Operation("Rooms", "POST", "/rooms/{room_id}/folders", "folder", {
        "room_id": _ROOM, "name": _f("Folder name"),
        "parent_id": _f("Optional parent folder ID", required=False),
    }, body=("name", "parent_id"), read_only=False),
    "list_room_murals": _Operation("Murals", "GET", "/rooms/{room_id}/murals", "murals", {
        "room_id": _ROOM, "status": _f("active or archived", required=False),
        "folder_id": _f("Filter by folder ID", required=False), "limit": _LIMIT, "next": _NEXT,
    }, query=("status", "folder_id", "limit", "next")),
    "list_workspace_murals": _Operation("Murals", "GET", "/workspaces/{workspace_id}/murals", "murals", {
        "workspace_id": _WORKSPACE, "status": _f("active or archived", required=False),
        "limit": _LIMIT, "next": _NEXT,
    }, query=("status", "limit", "next")),
    "get_mural": _Operation("Murals", "GET", "/murals/{mural_id}", "mural", {"mural_id": _MURAL}),
    "create_mural": _Operation("Murals", "POST", "/murals", "mural", {
        "room_id": _ROOM, "title": _f("Mural title"),
        "folder_id": _f("Optional destination folder", required=False),
        "infinite": _f("Borderless canvas", required=False, type=bool),
    }, body=("room_id", "title", "folder_id", "infinite"), read_only=False),
    "duplicate_mural": _Operation("Murals", "POST", "/murals/{mural_id}/duplicate", "mural", {
        "mural_id": _MURAL, "room_id": _ROOM, "title": _f("Title for the copy"),
        "folder_id": _f("Destination folder", required=False),
    }, body=("room_id", "title", "folder_id"), read_only=False),
    "update_mural": _Operation("Murals", "PATCH", "/murals/{mural_id}", "mural", {
        "mural_id": _MURAL, "title": _f("New mural title", required=False),
        "status": _f("active or archived", required=False),
        "folder_id": _f("Move to folder", required=False),
        "infinite": _f("Borderless canvas", required=False, type=bool),
    }, body=("title", "status", "folder_id", "infinite"), read_only=False),
    "delete_mural": _Operation("Murals", "DELETE", "/murals/{mural_id}", "deleted", {"mural_id": _MURAL}, read_only=False),
    "search_murals": _Operation("Search", "GET", "/search/{workspace_id}/murals", "murals", {
        "workspace_id": _WORKSPACE, "q": _f("Text to find"),
        "room_id": _f("Restrict to a room", required=False), "limit": _LIMIT, "next": _NEXT,
    }, query=("q", "room_id", "limit", "next")),
    "list_widgets": _Operation("Widgets", "GET", "/murals/{mural_id}/widgets", "widgets", {
        "mural_id": _MURAL, "type": _f("Comma-separated widget types", required=False),
        "limit": _LIMIT, "next": _NEXT,
    }, query=("type", "limit", "next")),
    "get_widget": _Operation("Widgets", "GET", "/murals/{mural_id}/widgets/{widget_id}", "widget", {
        "mural_id": _MURAL, "widget_id": _f("Widget ID"),
    }),
    "create_sticky_note": _Operation("Widgets", "POST", "/murals/{mural_id}/widgets/sticky-note", "widgets", {
        "mural_id": _MURAL, "text": _f("Sticky note text", widget="textarea"),
        "x": _f("Horizontal position in pixels", type=float),
        "y": _f("Vertical position in pixels", type=float),
        "shape": _f("rectangle or circle (defaults to rectangle)", required=False,
                    type=Literal["rectangle", "circle"]),
        "width": _f("Width in pixels", required=False, type=float),
        "height": _f("Height in pixels", required=False, type=float),
    }, body=("text", "x", "y", "shape", "width", "height"), read_only=False),
    "create_sticky_notes": _Operation("Widgets", "POST", "/murals/{mural_id}/widgets/sticky-note", "widgets", {
        "mural_id": _MURAL,
        "notes_json": _f("JSON array of up to 1,000 notes, each with text, x and y", widget="textarea"),
    }, read_only=False),
    "update_sticky_note": _Operation("Widgets", "PATCH", "/murals/{mural_id}/widgets/sticky-note/{widget_id}", "widget", {
        "mural_id": _MURAL, "widget_id": _f("Sticky note widget ID"),
        "text": _f("New text", required=False, widget="textarea"),
        "x": _f("New horizontal position", required=False, type=float),
        "y": _f("New vertical position", required=False, type=float),
    }, body=("text", "x", "y"), read_only=False),
    "delete_widget": _Operation("Widgets", "DELETE", "/murals/{mural_id}/widgets/{widget_id}", "deleted", {
        "mural_id": _MURAL, "widget_id": _f("Widget ID"),
    }, read_only=False),
    "create_comment": _Operation("Widgets", "POST", "/murals/{mural_id}/widgets/comment", "comment", {
        "mural_id": _MURAL, "message": _f("Comment text", widget="textarea"),
        "x": _f("Horizontal position", type=float), "y": _f("Vertical position", type=float),
        "reference_widget_id": _f("Widget to comment on", required=False),
    }, body=("message", "x", "y", "reference_widget_id"), read_only=False),
    "list_templates": _Operation("Templates", "GET", "/templates", "templates", {
        "limit": _LIMIT, "next": _NEXT,
    }, query=("limit", "next")),
    "list_workspace_templates": _Operation("Templates", "GET", "/workspaces/{workspace_id}/templates", "templates", {
        "workspace_id": _WORKSPACE, "without_default": _f("Only custom templates", required=False, type=bool),
        "limit": _LIMIT, "next": _NEXT,
    }, query=("without_default", "limit", "next")),
    "create_mural_from_template": _Operation("Templates", "POST", "/templates/{template_id}/murals", "mural", {
        "template_id": _f("Template ID"), "room_id": _ROOM,
        "title": _f("New mural title"), "folder_id": _f("Destination folder", required=False),
    }, body=("room_id", "title", "folder_id"), read_only=False),
    "create_template": _Operation("Templates", "POST", "/templates", "template", {
        "mural_id": _MURAL, "title": _f("Template title"),
        "description": _f("Template description", required=False),
    }, body=("mural_id", "title", "description"), read_only=False),
    "delete_template": _Operation("Templates", "DELETE", "/templates/{template_id}", "deleted", {
        "template_id": _f("Template ID"),
    }, read_only=False),
    "list_room_users": _Operation("Users", "GET", "/rooms/{room_id}/users", "users", {
        "room_id": _ROOM, "limit": _LIMIT, "next": _NEXT,
    }, query=("limit", "next")),
}

_DESCRIPTIONS = {
    "get_me": "Get the connected Mural user's profile.",
    "list_workspaces": "List workspaces available to the connected user.",
    "list_rooms": "List rooms in a workspace.",
    "get_room": "Get details of a room.",
    "create_room": "Create an open or private room in a workspace.",
    "update_room": "Change a room's name, description or privacy.",
    "delete_room": "Permanently delete a room owned by the user.",
    "list_folders": "List folders in a room.",
    "create_folder": "Create a folder in a room.",
    "list_room_murals": "List murals in a room.",
    "list_workspace_murals": "List murals in a workspace.",
    "get_mural": "Get a mural's details.",
    "create_mural": "Create a blank mural in a room.",
    "duplicate_mural": "Copy a mural to a room.",
    "update_mural": "Rename, archive, restore or move a mural.",
    "delete_mural": "Permanently delete a mural owned by the user.",
    "search_murals": "Search mural titles in a workspace.",
    "list_widgets": "List widgets on a mural, with pagination.",
    "get_widget": "Get one widget from a mural.",
    "create_sticky_note": "Add a sticky note at a position on a mural.",
    "create_sticky_notes": "Add up to 1,000 sticky notes in one request.",
    "update_sticky_note": "Change a sticky note's text or position.",
    "delete_widget": "Delete a widget and its content.",
    "create_comment": "Add a comment to a mural or widget.",
    "list_templates": "List Mural's default templates.",
    "list_workspace_templates": "List default and custom templates for a workspace.",
    "create_mural_from_template": "Create a mural from a template in a room.",
    "create_template": "Publish a custom template from an existing mural.",
    "delete_template": "Delete a custom template owned by the user.",
    "list_room_users": "List the members and guests of a room.",
}


def _config_model(name: str, operation: _Operation) -> type[BaseModel]:
    """Build one named Pydantic model per operation for the schema renderer."""
    fields: Dict[str, Any] = {
        "operation": (Literal[name], Field(name, title=name.replace("_", " ").title(),
                         json_schema_extra={"const": name, "ui:hidden": True,
                                            "x-category": operation.category,
                                            "x-display-name": name.replace("_", " ").title(),
                                            "x-is-trigger": False}))
    }
    option_fields = dict(operation.fields)
    # A mural or room can be supplied directly. Optional context fields also
    # let the editor populate its cascading pickers when the operation itself
    # does not otherwise need the parent ID.
    if "mural_id" in option_fields and "room_id" not in option_fields:
        option_fields["room_id"] = _f(
            "Room for the mural picker (optional)", required=False,
            dynamic="room_id", depends_on="workspace_id", type=int,
        )
    if "room_id" in option_fields and "workspace_id" not in option_fields:
        option_fields["workspace_id"] = _f(
            "Workspace for the room picker (optional)", required=False,
            dynamic="workspace_id",
        )
    for key, spec in option_fields.items():
        extra: Dict[str, Any] = {}
        if spec.dynamic:
            dyn = {"field_name": key, "placeholder": f"Select {key.replace('_', ' ')}...",
                   "searchable": True, "allow_custom": True}
            if spec.depends_on:
                dyn["depends_on"] = spec.depends_on
            extra["x-dynamic-options"] = dyn
        if spec.widget:
            extra["ui:widget"] = spec.widget
        annotation = spec.type if spec.required else Optional[spec.type]
        fields[key] = (annotation, Field(... if spec.required else None,
                       title=key.replace("_", " ").title(), description=spec.description,
                       json_schema_extra=extra or None))
    return create_model("Mural" + "".join(part.title() for part in name.split("_")) + "Config",
                        __doc__=_DESCRIPTIONS[name], **fields)


_CONFIG_MODELS = tuple(_config_model(name, op) for name, op in OPERATIONS.items())
globals().update({model.__name__: model for model in _CONFIG_MODELS})
MuralConfig = Annotated[Union[_CONFIG_MODELS], Discriminator("operation")]


class MuralNodeConfig(NodeConfig[MuralConfig, MuralOAuthCredential]):
    """One selected Mural operation plus the connected account."""


_API_NAMES = {"workspace_id": "workspaceId", "room_id": "roomId", "folder_id": "folderId",
              "mural_id": "muralId", "parent_id": "parentId",
              "reference_widget_id": "referenceWidgetId", "without_default": "withoutDefault"}


def _api_name(name: str) -> str:
    return _API_NAMES.get(name, name)


def _url_path(template: str, config: BaseModel) -> str:
    path = template
    for name in config.model_fields:
        marker = "{" + name + "}"
        if marker in path:
            value = getattr(config, name)
            if value is None or str(value).strip() == "":
                raise ValueError(f"{name} is required")
            path = path.replace(marker, quote(str(value), safe=""))
    return path


def _body(operation_name: str, spec: _Operation, config: BaseModel) -> Any:
    if operation_name == "create_sticky_notes":
        try:
            notes = json.loads(config.notes_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("notes_json must be a JSON array") from exc
        if not isinstance(notes, list) or not 1 <= len(notes) <= 1000 or not all(isinstance(n, dict) for n in notes):
            raise ValueError("notes_json must contain 1 to 1,000 note objects")
        if any(not all(key in note for key in ("text", "x", "y")) for note in notes):
            raise ValueError("Each note must include text, x and y")
        if any(note.get("shape", "rectangle") not in ("rectangle", "circle") for note in notes):
            raise ValueError("Each note shape must be rectangle or circle")
        return [{**note, "shape": note.get("shape") or "rectangle"} for note in notes]
    body = {_api_name(name): getattr(config, name) for name in spec.body
            if getattr(config, name, None) is not None}
    if "roomId" in body:
        body["roomId"] = int(body["roomId"])
    if operation_name == "create_sticky_note":
        body["shape"] = body.get("shape") or "rectangle"
        return [body]
    if spec.method in ("POST", "PATCH") and not body:
        raise ValueError("At least one field to write is required")
    return body or None


class MuralNode(WorkflowNode):
    """Read and manage Mural workspaces, rooms, murals, templates and widgets."""

    integration_type = "automation-mural"

    edit_examples = [
        "Create a mural from a workshop template",
        "Add sticky notes to a mural from form submissions",
        "List the murals in my workspace",
        "Archive a mural after the project closes",
    ]
    connection_evidence = ConnectionEvidence(field="workspace_id", noun="workspaces", identity_operation="get_me")
    scope_registry = MURAL_SCOPE_REGISTRY

    @classmethod
    def get_config_model(cls):
        return MuralNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.mural_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="mural",
        )

    async def _ensure_fresh_token(self, credential: MuralOAuthCredential) -> None:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.mural_oauth import refresh_access_token
        data = credential.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=data, refresh=refresh_access_token, provider="mural", caller_path="execute",
        )
        credential.access_token = data["access_token"]
        credential.refresh_token = data.get("refresh_token") or credential.refresh_token
        credential.expires_at = data.get("expires_at")

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: Dict[str, Any],
                                 context: Optional[Dict[str, Any]] = None,
                                 page_token: Optional[str] = None,
                                 search: Optional[str] = None) -> Dict[str, Any]:
        # Credential loaders call freshen_credential before passing this snapshot.
        token = require_credential_token(
            (credential_data or {}).get("access_token"),
            "Connect a Mural account to load options",
        )
        ctx = context or {}
        if field_name == "workspace_id":
            path = "/workspaces"
        elif field_name == "room_id" and ctx.get("workspace_id"):
            path = f"/workspaces/{quote(str(ctx['workspace_id']), safe='')}/rooms"
        elif field_name == "mural_id" and ctx.get("room_id"):
            path = f"/rooms/{quote(str(ctx['room_id']), safe='')}/murals"
        else:
            return {"options": [], "next_page_token": None}
        params = {"limit": 100}
        if page_token:
            params["next"] = page_token
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(MURAL_API_BASE + path,
                                        headers={"Authorization": f"Bearer {token}"}, params=params)
            response.raise_for_status()
            payload = response.json()
        items = payload.get("value", [])
        if not isinstance(items, list):
            items = []
        options = [{"value": str(item.get("id")), "label": str(item.get("title") or item.get("name") or item.get("id"))}
                   for item in items if isinstance(item, dict) and item.get("id") is not None]
        if search:
            options = [item for item in options if search.lower() in item["label"].lower()]
        return {"options": options, "next_page_token": payload.get("next")}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, MuralNodeConfig):
            raise ValueError("Valid Mural configuration is required")
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Mural account")
        await self._ensure_fresh_token(credential)
        config = self.config.config
        name = config.operation
        spec = OPERATIONS[name]
        path = _url_path(spec.path, config)
        params = {_api_name(key): getattr(config, key) for key in spec.query
                  if getattr(config, key, None) is not None}
        body = _body(name, spec, config)
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(spec.method, MURAL_API_BASE + path,
                                                headers={"Authorization": f"Bearer {credential.access_token}",
                                                         "Accept": "application/json"},
                                                params=params or None, json=body)
            elapsed = round((time.monotonic() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    error = response.json()
                except ValueError:
                    error = {"message": response.text[:500]}
                return {"status": "error", "action": name, "status_code": response.status_code,
                        "error": error.get("message", str(error)) if isinstance(error, dict) else str(error),
                        "timing_ms": {"api_request": elapsed}}
            payload = response.json() if response.content else {}
            value = payload.get("value", payload) if isinstance(payload, dict) else payload
            result = {spec.result: value}
            if isinstance(payload, dict) and payload.get("next"):
                result["next_page_token"] = payload["next"]
            return {"status": "success", "action": name, "data": result,
                    "status_code": response.status_code, "timing_ms": {"api_request": elapsed}}
        except httpx.TimeoutException:
            return {"status": "error", "action": name, "status_code": 408,
                    "error": "Mural request timed out",
                    "timing_ms": {"api_request": round((time.monotonic() - start) * 1000, 2)}}
        except httpx.RequestError:
            logger.exception("Mural API request failed for %s", name)
            return {"status": "error", "action": name, "status_code": 502,
                    "error": "Could not reach the Mural API",
                    "timing_ms": {"api_request": round((time.monotonic() - start) * 1000, 2)}}
