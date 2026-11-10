"""Miro board, item, member and tag workflow operations."""

import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.miro_operations import OPERATIONS as BOARD_API_OPERATIONS, BoardOperation
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.oauth.miro_oauth import get_token_context
from nodes.scopes.miro import MIRO_SCOPES


def _operation(name: str, label: str, category: str, **extra: Any) -> Any:
    return Field(name, title=label, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category,
        "x-is-trigger": False, "x-display-name": label, **extra,
    })


def _board_field() -> Any:
    return Field(..., title="Board", json_schema_extra={"x-dynamic-options": {
        "field_name": "board_id", "placeholder": "Select a board…",
        "searchable": True, "allow_custom": True, "custom_placeholder": "Or paste board ID",
    }})


class MiroOAuthCredential(BaseModel):
    credential_type: Literal["miro_oauth"] = Field("miro_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    team_id: Optional[str] = Field(None, title="Team ID")
    user_id: Optional[str] = Field(None, title="User ID")
    model_config = ConfigDict(title="Miro OAuth", json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "miro",
        "x-oauth-scopes": MIRO_SCOPES.declared_scopes(),
        "x-credential-url": "https://miro.com/app/settings/user-profile/apps",
    })


class GetTokenContext(BaseModel):
    """Identify the connected Miro user and team."""
    operation: Literal["get_token_context"] = _operation("get_token_context", "Get Connected Account", "Account")


class ListBoards(BaseModel):
    """List boards accessible to the connected user."""
    operation: Literal["list_boards"] = _operation("list_boards", "List Boards", "Boards")
    limit: int = Field(50, ge=1, le=50, title="Page Size")
    offset: int = Field(0, ge=0, title="Offset")
    query: Optional[str] = Field(None, title="Search")


class GetBoard(BaseModel):
    """Read a board's details and sharing settings."""
    operation: Literal["get_board"] = _operation("get_board", "Get Board", "Boards")
    board_id: str = _board_field()


class CreateBoard(BaseModel):
    """Create a board in the connected Miro team."""
    operation: Literal["create_board"] = _operation("create_board", "Create Board", "Boards", **{
        "x-creates-resource": True, "x-resource-type": "miro_board", "x-resource-id-path": "data.id",
    })
    name: str = Field(..., min_length=1, max_length=60, title="Board Name")
    description: Optional[str] = Field(None, max_length=300, title="Description")


class UpdateBoard(BaseModel):
    """Rename a board or change its description."""
    operation: Literal["update_board"] = _operation("update_board", "Update Board", "Boards")
    board_id: str = _board_field()
    name: Optional[str] = Field(None, min_length=1, max_length=60, title="New Name")
    description: Optional[str] = Field(None, max_length=300, title="New Description")


class DeleteBoard(BaseModel):
    """Permanently delete a Miro board."""
    operation: Literal["delete_board"] = _operation("delete_board", "Delete Board", "Boards")
    board_id: str = _board_field()


class ListBoardMembers(BaseModel):
    """List people who have access to a board."""
    operation: Literal["list_board_members"] = _operation("list_board_members", "List Board Members", "Members")
    board_id: str = _board_field()
    limit: int = Field(50, ge=1, le=50, title="Page Size")


class ShareBoard(BaseModel):
    """Invite an email address to a board."""
    operation: Literal["share_board"] = _operation("share_board", "Share Board", "Members")
    board_id: str = _board_field()
    email: str = Field(..., title="Invitee Email")
    role: Literal["viewer", "editor", "commenter"] = Field("viewer", title="Role")
    message: Optional[str] = Field(None, title="Invitation Message")


class ListItems(BaseModel):
    """List items on a board, optionally by type or tag."""
    operation: Literal["list_items"] = _operation("list_items", "List Board Items", "Items")
    board_id: str = _board_field()
    limit: int = Field(50, ge=1, le=50, title="Page Size")
    cursor: Optional[str] = Field(None, title="Next Page Cursor")
    item_type: Optional[str] = Field(None, title="Item Type", description="For example sticky_note, card, or text")
    tag_id: Optional[str] = Field(None, title="Tag ID")


class GetItem(BaseModel):
    """Read any item on a board by ID."""
    operation: Literal["get_item"] = _operation("get_item", "Get Item", "Items")
    board_id: str = _board_field()
    item_id: str = Field(..., title="Item ID")


class CreateStickyNote(BaseModel):
    """Add a sticky note to a board."""
    operation: Literal["create_sticky_note"] = _operation("create_sticky_note", "Create Sticky Note", "Items", **{
        "x-creates-resource": True, "x-resource-type": "miro_item", "x-resource-id-path": "data.id",
    })
    board_id: str = _board_field()
    content: str = Field(..., max_length=6000, title="Content", json_schema_extra={"ui:widget": "textarea"})
    x: float = Field(0, title="X Position")
    y: float = Field(0, title="Y Position")


class UpdateStickyNote(BaseModel):
    """Change the content of an existing sticky note."""
    operation: Literal["update_sticky_note"] = _operation("update_sticky_note", "Update Sticky Note", "Items")
    board_id: str = _board_field()
    item_id: str = Field(..., title="Sticky Note ID")
    content: str = Field(..., max_length=6000, title="Content", json_schema_extra={"ui:widget": "textarea"})


class CreateCard(BaseModel):
    """Create a Miro task card with a title and description."""
    operation: Literal["create_card"] = _operation("create_card", "Create Card", "Items", **{
        "x-creates-resource": True, "x-resource-type": "miro_item", "x-resource-id-path": "data.id",
    })
    board_id: str = _board_field()
    title: str = Field(..., title="Title")
    description: Optional[str] = Field(None, title="Description", json_schema_extra={"ui:widget": "textarea"})


class UpdateCard(BaseModel):
    """Update a card's title or description."""
    operation: Literal["update_card"] = _operation("update_card", "Update Card", "Items")
    board_id: str = _board_field()
    item_id: str = Field(..., title="Card ID")
    title: Optional[str] = Field(None, title="New Title")
    description: Optional[str] = Field(None, title="New Description")


class CreateText(BaseModel):
    """Add a text item to a Miro board."""
    operation: Literal["create_text"] = _operation("create_text", "Create Text", "Items", **{
        "x-creates-resource": True, "x-resource-type": "miro_item", "x-resource-id-path": "data.id",
    })
    board_id: str = _board_field()
    content: str = Field(..., title="Content", json_schema_extra={"ui:widget": "textarea"})


class DeleteItem(BaseModel):
    """Remove an item from a board."""
    operation: Literal["delete_item"] = _operation("delete_item", "Delete Item", "Items")
    board_id: str = _board_field()
    item_id: str = Field(..., title="Item ID")


class ListTags(BaseModel):
    """List the tags defined on a board."""
    operation: Literal["list_tags"] = _operation("list_tags", "List Board Tags", "Tags")
    board_id: str = _board_field()


class GetTag(BaseModel):
    """Read one board tag."""
    operation: Literal["get_tag"] = _operation("get_tag", "Get Tag", "Tags")
    board_id: str = _board_field()
    tag_id: str = Field(..., title="Tag ID")


class ListItemTags(BaseModel):
    """List tags attached to an item."""
    operation: Literal["list_item_tags"] = _operation("list_item_tags", "List Item Tags", "Tags")
    board_id: str = _board_field()
    item_id: str = Field(..., title="Item ID")


class CreateTag(BaseModel):
    """Create a board tag to categorize cards or sticky notes."""
    operation: Literal["create_tag"] = _operation("create_tag", "Create Tag", "Tags", **{
        "x-creates-resource": True, "x-resource-type": "miro_tag", "x-resource-id-path": "data.id",
    })
    board_id: str = _board_field()
    title: str = Field(..., max_length=120, title="Tag Title")
    fill_color: Literal[
        "red", "magenta", "violet", "light_green", "green", "dark_green",
        "cyan", "blue", "dark_blue", "yellow", "gray", "black",
    ] = Field("red", title="Tag Color")


class AttachTag(BaseModel):
    """Attach an existing tag to a card or sticky note."""
    operation: Literal["attach_tag"] = _operation("attach_tag", "Attach Tag", "Tags")
    board_id: str = _board_field()
    item_id: str = Field(..., title="Item ID")
    tag_id: str = Field(..., title="Tag ID")


class RemoveTag(BaseModel):
    """Remove an attached tag from a card or sticky note."""
    operation: Literal["remove_tag"] = _operation("remove_tag", "Remove Tag", "Tags")
    board_id: str = _board_field()
    item_id: str = Field(..., title="Item ID")
    tag_id: str = Field(..., title="Tag ID")


# Miro's own MCP server: agents get its tools through a person's Miro sign-in.
MiroMcpCredential = mcp_credential("miro", "https://mcp.miro.com", app="Miro")
MiroCredential = Union[MiroOAuthCredential, MiroMcpCredential]


REQUIRED_QUERY_FIELDS: dict[str, dict[str, type]] = {
    "api_copy_board": {"copy_from": str},
    "api_getitemsbygroupid": {"group_item_id": str},
    "api_deletegroup": {"delete_items": bool},
}


def _make_board_api_config(name: str, op: BoardOperation) -> type[BaseModel]:
    """Expose each official board endpoint as a selectable workflow action."""
    fields: dict[str, tuple[Any, Any]] = {}
    for param in re.findall(r"\{([^}]+)\}", op.path):
        fields[param] = (str, Field(..., title=param.replace("_", " ").title()))
    for param, typ in REQUIRED_QUERY_FIELDS.get(name, {}).items():
        fields[param] = (typ, Field(..., title=param.replace("_", " ").title()))
    fields["query_json"] = (Optional[str], Field(
        None, title="Query Parameters JSON",
        description="Optional Miro filters and pagination as a JSON object.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    ))
    if op.body_type == "application/json":
        fields["body_json"] = (str if op.body_required else Optional[str], Field(
            ... if op.body_required else None, title="Request Body JSON",
            description=op.description or "Miro request body as JSON.",
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
        ))
    return create_model(
        "Miro" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(Literal[name], _operation(name, op.label, op.category)),
        **fields,
    )


BOARD_API_CONFIGS = {name: _make_board_api_config(name, op) for name, op in BOARD_API_OPERATIONS.items()}
globals().update({model.__name__: model for model in BOARD_API_CONFIGS.values()})


class MiroOnNewBoardConfig(PollTriggerConfigBase):
    """Watch team boards: https://developers.miro.com/reference/get-boards-1"""
    operation: Literal["on_new_board"] = _operation(
        "on_new_board", "On New Board", "Triggers", **{"x-is-trigger": True})
    team_id: str = Field(..., min_length=1, title="Team ID",
                         description="The Miro team whose accessible boards to monitor.")


class MiroOnNewOrUpdatedBoardConfig(PollTriggerConfigBase):
    """Watch team board changes: https://developers.miro.com/reference/get-boards-1"""
    operation: Literal["on_new_or_updated_board"] = _operation(
        "on_new_or_updated_board", "On New or Updated Board", "Triggers", **{"x-is-trigger": True})
    team_id: str = Field(..., min_length=1, title="Team ID",
                         description="The Miro team whose accessible boards to monitor.")


MiroConfig = Annotated[Union[tuple([
    GetTokenContext, ListBoards, GetBoard, CreateBoard, UpdateBoard, DeleteBoard,
    ListBoardMembers, ShareBoard, ListItems, GetItem, CreateStickyNote,
    UpdateStickyNote, CreateCard, UpdateCard, CreateText, DeleteItem,
    ListTags, GetTag, ListItemTags, CreateTag, AttachTag, RemoveTag,
    MiroOnNewBoardConfig, MiroOnNewOrUpdatedBoardConfig, *BOARD_API_CONFIGS.values(),
])], Discriminator("operation")]


class MiroNodeConfig(NodeConfig[MiroConfig, MiroCredential]):
    pass


class MiroNode(ScheduledPollTriggerMixin, WorkflowNode):
    """Run Miro board and item operations with the connected user's OAuth token."""

    integration_type = "automation-miro"
    credential_provider_labels = {"miro": "Miro Account"}

    connection_evidence = ConnectionEvidence(operation="list_boards", noun="boards", identity_operation="get_token_context")
    scope_registry = MIRO_SCOPES
    edit_examples = [
        "List my Miro boards", "Add a sticky note to a Miro board",
        "Create a Miro board for a project", "Share a Miro board with a teammate",
    ]

    @classmethod
    def get_config_model(cls):
        return MiroNodeConfig

    @classmethod
    def should_propagate_output(cls, output: dict[str, Any], config: dict[str, Any]) -> bool:
        if config.get("operation") in {"on_new_board", "on_new_or_updated_board"}:
            return bool(output.get("board_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output: dict[str, Any]) -> Optional[dict[str, Any]]:
        if output.get("operation") not in {"on_new_board", "on_new_or_updated_board"}:
            return super().resolve_agent_event(output)
        boards = output.get("boards", [])
        if not boards:
            return None
        updated = output["operation"] == "on_new_or_updated_board"
        lines = []
        for board in boards[:10]:
            actor = (board.get("modifiedBy" if updated else "createdBy") or {}).get("name") or "Someone"
            action = "created or updated" if updated else "created"
            lines.append(f"- {actor} {action} {board.get('name') or 'Untitled board'} "
                         f"(board ID: {board['id']}, team ID: {output['team_id']}). "
                         f"{board.get('description') or ''} {board.get('viewLink') or ''}")
        if len(boards) > 10:
            lines.append(f"- … and {len(boards) - 10} more boards")
        return {"text": "Miro board activity:\n" + "\n".join(lines), "conversation_key": None}

    async def _poll_boards(self, token: str, config) -> dict[str, Any]:
        # Miro retired experimental webhooks on December 5, 2025:
        # https://developers.miro.com/changelog/removed-experimental-webhooks-support
        # Sorting requires a team or project: always send the declared team.
        updated = isinstance(config, MiroOnNewOrUpdatedBoardConfig)
        boards = []
        offset = 0
        while True:
            payload = await self._request(token, "GET", "/boards", params={
                "team_id": config.team_id, "sort": "last_modified" if updated else "last_created",
                "limit": 50, "offset": offset,
            })
            page = payload.get("data", [])
            boards.extend(board for board in page if isinstance(board, dict))
            offset += len(page)
            total = payload.get("total")
            if not page or (isinstance(total, int) and offset >= total) or (total is None and len(page) < 50):
                break
            if offset >= 10000:
                raise ValueError("Miro team has too many boards to monitor safely (maximum 10,000)")
        if len(boards) > 10000:
            raise ValueError("Miro team has too many boards to monitor safely (maximum 10,000)")
        fresh = await self._filter_unseen(
            boards, lambda board: (json.dumps([board["id"], board.get("modifiedAt")])
                                   if updated else str(board["id"])) if board.get("id") else None)
        return {"operation": config.operation, "boards": fresh, "board_count": len(fresh),
                "team_id": config.team_id}

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.miro_oauth import refresh_access_token
        if not credential_data.get("refresh_token"):
            return credential_data
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="miro",
            additional_token_fields=("team_id", "user_id"))

    async def _token(self, credential: MiroOAuthCredential) -> str:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.miro_oauth import refresh_access_token
        data = credential.model_dump()
        if data.get("refresh_token"):
            await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
                credential=data, refresh=refresh_access_token, provider="miro", caller_path="execute",
                additional_token_fields=("team_id", "user_id"))
            for key in ("access_token", "refresh_token", "expires_at", "team_id", "user_id"):
                if key in data:
                    setattr(credential, key, data[key])
        return data["access_token"]

    @staticmethod
    async def _request(token: str, method: str, path: str, *, params=None, body=None) -> Any:
        params = {key: value for key, value in (params or {}).items() if value is not None}
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(method, f"https://api.miro.com{path if path.startswith(('/v2/', '/v2-experimental/')) else '/v2' + path}",
                                            params=params, json=body,
                                            headers={"Authorization": f"Bearer {token}"})
        if response.is_error:
            try:
                data = response.json()
                detail = data.get("message") or data.get("error", {}).get("message")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Miro API error {response.status_code}: {detail or 'request failed'}")
        if not response.content:
            return {"ok": True}
        if "json" in response.headers.get("content-type", "") or response.content[:1] in (b"{", b"["):
            return response.json()
        return BinaryOutput(
            data=response.content,
            content_type=response.headers.get("content-type", "application/octet-stream"),
            filename="miro-download",
        )

    @staticmethod
    def _parse_json(raw: Optional[str], label: str) -> Any:
        try:
            return json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} must be valid JSON") from exc

    @classmethod
    def _parse_object(cls, raw: Optional[str], label: str) -> dict[str, Any]:
        value = cls._parse_json(raw, label)
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be a JSON object")
        return value

    @classmethod
    async def load_field_options(
        cls, field_name: str, credential_data: dict, context=None,
        page_token: Optional[str] = None, search: Optional[str] = None,
    ) -> list[dict]:
        if field_name != "board_id":
            return []
        params = {"limit": 50, "query": search}
        if page_token:
            try:
                params["offset"] = max(0, int(page_token))
            except ValueError as exc:
                raise ValueError("Invalid board page token") from exc
        payload = await cls._request(credential_data["access_token"], "GET", "/boards", params=params)
        return [{"value": board["id"], "label": board.get("name") or board["id"]}
                for board in payload.get("data", []) if board.get("id")]

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, MiroNodeConfig):
            raise ValueError("Miro configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Miro account")
        op = self.config.config
        name = op.operation
        self.scope_registry.require(name)
        token = await self._token(credential)
        if isinstance(op, (MiroOnNewBoardConfig, MiroOnNewOrUpdatedBoardConfig)):
            return await self._poll_boards(token, op)
        if isinstance(op, GetTokenContext):
            return {"status": "success", "operation": name, "data": await get_token_context(token)}

        if name in BOARD_API_OPERATIONS:
            spec = BOARD_API_OPERATIONS[name]
            values = op.model_dump(exclude_none=True, exclude={"operation"})
            path = spec.path
            for param in re.findall(r"\{([^}]+)\}", path):
                path = path.replace("{" + param + "}", quote(str(values.pop(param)), safe=""))
            params = self._parse_object(values.pop("query_json", None), "Query Parameters JSON")
            for param in REQUIRED_QUERY_FIELDS.get(name, {}):
                value = values.pop(param)
                params[param] = str(value).lower() if isinstance(value, bool) else value
            raw_body = values.pop("body_json", None)
            body = (self._parse_json(raw_body, "Request Body JSON")
                    if spec.body_type == "application/json" and raw_body is not None else None)
            data = await self._request(token, spec.method, path, params=params, body=body)
            return {"status": "success", "operation": name, "data": data}

        method, path, params, body = "GET", "", None, None
        board = f"/boards/{quote(op.board_id, safe='')}" if hasattr(op, "board_id") else ""
        item = f"{board}/items/{quote(op.item_id, safe='')}" if hasattr(op, "item_id") else ""
        tag = f"{board}/tags/{quote(op.tag_id, safe='')}" if getattr(op, "tag_id", None) else ""
        if isinstance(op, ListBoards):
            path, params = "/boards", {"limit": op.limit, "offset": op.offset, "query": op.query}
        elif isinstance(op, GetBoard):
            path = board
        elif isinstance(op, CreateBoard):
            method, path, body = "POST", "/boards", {"name": op.name}
            if op.description is not None:
                body["description"] = op.description
        elif isinstance(op, UpdateBoard):
            method, path, body = "PATCH", board, op.model_dump(exclude={"operation", "board_id"}, exclude_none=True)
            if not body:
                raise ValueError("Provide a name or description to update")
        elif isinstance(op, DeleteBoard):
            method, path = "DELETE", board
        elif isinstance(op, ListBoardMembers):
            path, params = f"{board}/members", {"limit": op.limit}
        elif isinstance(op, ShareBoard):
            method, path = "POST", f"{board}/members"
            body = {"emails": [op.email], "role": op.role}
            if op.message:
                body["message"] = op.message
        elif isinstance(op, ListItems):
            path, params = f"{board}/items", {"limit": op.limit, "cursor": op.cursor, "type": op.item_type, "tag_id": op.tag_id}
        elif isinstance(op, GetItem):
            path = item
        elif isinstance(op, CreateStickyNote):
            method, path = "POST", f"{board}/sticky_notes"
            body = {"data": {"content": op.content}, "position": {"x": op.x, "y": op.y}}
        elif isinstance(op, UpdateStickyNote):
            method, path, body = "PATCH", f"{board}/sticky_notes/{quote(op.item_id, safe='')}", {"data": {"content": op.content}}
        elif isinstance(op, CreateCard):
            method, path = "POST", f"{board}/cards"
            body = {"data": {"title": op.title, "description": op.description or ""}}
        elif isinstance(op, UpdateCard):
            method, path = "PATCH", f"{board}/cards/{quote(op.item_id, safe='')}"
            body = {"data": op.model_dump(exclude={"operation", "board_id", "item_id"}, exclude_none=True)}
            if not body["data"]:
                raise ValueError("Provide a title or description to update")
        elif isinstance(op, CreateText):
            method, path, body = "POST", f"{board}/texts", {"data": {"content": op.content}}
        elif isinstance(op, DeleteItem):
            method, path = "DELETE", item
        elif isinstance(op, ListTags):
            path = f"{board}/tags"
        elif isinstance(op, GetTag):
            path = tag
        elif isinstance(op, ListItemTags):
            path = f"{item}/tags"
        elif isinstance(op, CreateTag):
            method, path, body = "POST", f"{board}/tags", {
                "title": op.title, "fillColor": op.fill_color,
            }
        elif isinstance(op, AttachTag):
            method, path, params = "POST", item, {"tag_id": op.tag_id}
        elif isinstance(op, RemoveTag):
            method, path, params = "DELETE", item, {"tag_id": op.tag_id}
        else:
            raise ValueError(f"Unsupported Miro operation: {name}")
        data = await self._request(token, method, path, params=params, body=body)
        return {"status": "success", "operation": name, "data": data}
