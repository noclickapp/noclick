"""
Trello project-management automation node.

Provides workflow integration with the Trello REST API (v1) for operations on
boards, lists, cards, checklists, members, labels, and webhooks.

Authentication: API key + user token, passed as `?key=&token=` query params.
Trello's classic REST API uses OAuth 1.0a, NOT OAuth 2.0; the API key + token
flow is the supported path for a self-serve automation node.

API Base URL: https://api.trello.com/1
Documentation: https://developer.atlassian.com/cloud/trello/rest/

Webhooks: Trello exposes a registerable webhook API
(`POST /tokens/{token}/webhooks/`). Each callback carries an `X-Trello-Webhook`
header = base64(HMAC-SHA1(request_body + callbackURL, api_secret)).
"""

import base64
import hashlib
import hmac
import logging
import time
from typing import Dict, Any, Optional, List, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, Discriminator
import httpx

from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

logger = logging.getLogger(__name__)

TRELLO_API_BASE = "https://api.trello.com/1"

# Models the webhook trigger can watch (board, card, list, member).
WEBHOOK_MODEL_TYPES = ["board", "card", "list", "member"]

# Trello webhook event types. A Trello webhook fires on EVERY change to the
# watched model with no per-subscription filter — the specific event lives at
# ``action.type`` in the delivered payload. The trigger therefore subscribes to
# everything and filters at runtime (see ``filter_trigger_payload``). The "*"
# sentinel means "any change". (action.type reference:
# https://developer.atlassian.com/cloud/trello/guides/rest-api/action-types/)

# Board-level events: all action types delivered when watching a board model.
TRELLO_BOARD_EVENTS: List[str] = [
    "*",
    "createCard",
    "updateCard",
    "deleteCard",
    "moveCardToBoard",
    "moveCardFromBoard",
    "copyCard",
    "emailCard",
    "commentCard",
    "addAttachmentToCard",
    "deleteAttachmentFromCard",
    "addMemberToCard",
    "removeMemberFromCard",
    "addChecklistToCard",
    "removeChecklistFromCard",
    "updateCheckItemStateOnCard",
    "createList",
    "updateList",
    "moveListToBoard",
    "moveListFromBoard",
    "updateBoard",
    "addMemberToBoard",
]

TRELLO_BOARD_EVENT_LABELS: List[str] = [
    "Any change on the board",
    "Card created",
    "Card updated (moved, renamed, due date, archived)",
    "Card deleted",
    "Card moved to this board",
    "Card moved off this board",
    "Card copied",
    "Card created via email",
    "Comment added to card",
    "Attachment added to card",
    "Attachment removed from card",
    "Member added to card",
    "Member removed from card",
    "Checklist added to card",
    "Checklist removed from card",
    "Checklist item checked/unchecked",
    "List created",
    "List updated (renamed, archived)",
    "List moved to this board",
    "List moved off this board",
    "Board updated (name, description, settings)",
    "Member added to board",
]

# Card-level events: action types delivered when watching a specific card model.
TRELLO_CARD_EVENTS: List[str] = [
    "*",
    "updateCard",
    "deleteCard",
    "copyCard",
    "commentCard",
    "addAttachmentToCard",
    "deleteAttachmentFromCard",
    "addMemberToCard",
    "removeMemberFromCard",
    "addChecklistToCard",
    "removeChecklistFromCard",
    "updateCheckItemStateOnCard",
]

TRELLO_CARD_EVENT_LABELS: List[str] = [
    "Any card change",
    "Card updated (renamed, moved, due date, archived)",
    "Card deleted",
    "Card copied",
    "Comment added",
    "Attachment added",
    "Attachment removed",
    "Member added to card",
    "Member removed from card",
    "Checklist added",
    "Checklist removed",
    "Checklist item checked/unchecked",
]


# ============================================================================
# Credential Schema
# ============================================================================


class TrelloApiKeyCredential(BaseModel):
    """API key + token credential for Trello.

    The API key is public; the token is secret and grants account access. The
    optional API secret is only needed to verify inbound webhook signatures.
    """

    credential_type: Literal["trello_api_key"] = Field(
        "trello_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        description="Trello API key from a Power-Up at trello.com/power-ups/admin -> API Key tab",
        json_schema_extra={"ui:widget": "password"},
    )
    api_token: str = Field(
        ...,
        title="API Token",
        description="User token generated via trello.com/1/authorize (scope read,write,account)",
        json_schema_extra={"ui:widget": "password"},
    )
    api_secret: Optional[str] = Field(
        None,
        title="API Secret (optional)",
        description="Power-Up OAuth secret. Only required to verify webhook trigger signatures.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        json_schema_extra={"x-credential-url": "https://trello.com/power-ups/admin"}
    )


TrelloCredential = TrelloApiKeyCredential


# ============================================================================
# Operation Configs
# ============================================================================


class TrelloSearchConfig(BaseModel):
    """Search across boards, cards, and members."""

    operation: Literal["search"] = Field(
        "search",
        json_schema_extra={
            "const": "search",
            "ui:hidden": True,
            "x-category": "Search",
            "x-is-trigger": False,
            "x-display-name": "Search",
        },
        title="Search",
    )
    query: str = Field(..., title="Query", description="Search text (e.g. a card name or keyword)")
    model_types: Optional[str] = Field(
        "all",
        title="Types",
        description="Comma-separated model types to search",
        json_schema_extra={
            "enum": ["all", "actions", "boards", "cards", "members", "organizations"],
            "enumNames": ["All", "Actions", "Boards", "Cards", "Members", "Organizations"],
            "x-enum-searchable": True,
        },
    )


class TrelloGetMeConfig(BaseModel):
    """Get the authenticated member's profile."""

    operation: Literal["get_me"] = Field(
        "get_me",
        json_schema_extra={
            "const": "get_me",
            "ui:hidden": True,
            "x-category": "Members",
            "x-is-trigger": False,
            "x-display-name": "Get Authenticated Member",
        },
        title="Get Authenticated Member",
    )


class TrelloGetMemberBoardsConfig(BaseModel):
    """List boards belonging to a member."""

    operation: Literal["get_member_boards"] = Field(
        "get_member_boards",
        json_schema_extra={
            "const": "get_member_boards",
            "ui:hidden": True,
            "x-category": "Members",
            "x-is-trigger": False,
            "x-display-name": "Get Member's Boards",
        },
        title="Get Member's Boards",
    )
    member_id: str = Field(
        "me", title="Member ID", description="Member ID or 'me' for the current user"
    )


class TrelloGetBoardConfig(BaseModel):
    """Retrieve a single board's details."""

    operation: Literal["get_board"] = Field(
        "get_board",
        json_schema_extra={
            "const": "get_board",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Get Board",
        },
        title="Get Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to retrieve",
        json_schema_extra={
            "x-resource-type": "trello_board",
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste board ID",
            }
        },
    )


class TrelloCreateBoardConfig(BaseModel):
    """Create a new board."""

    operation: Literal["create_board"] = Field(
        "create_board",
        json_schema_extra={
            "const": "create_board",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Create Board",
            "x-creates-resource": True,
            "x-resource-type": "trello_board",
            "x-resource-id-path": "data.id",
        },
        title="Create Board",
    )
    name: str = Field(..., title="Name", description="Name of the new board")
    id_organization: Optional[str] = Field(
        None, title="Organization ID", description="Workspace/organization to create the board in"
    )
    default_lists: Optional[str] = Field(
        "true",
        title="Default Lists",
        description="Create the default To Do / Doing / Done lists",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class TrelloUpdateBoardConfig(BaseModel):
    """Update an existing board."""

    operation: Literal["update_board"] = Field(
        "update_board",
        json_schema_extra={
            "const": "update_board",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Update Board",
        },
        title="Update Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to update",
        json_schema_extra={
            "x-resource-type": "trello_board",
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste board ID",
            }
        },
    )
    name: Optional[str] = Field(None, title="Name", description="New board name")
    desc: Optional[str] = Field(
        None,
        title="Description",
        description="New board description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    closed: Optional[str] = Field(
        None,
        title="Closed",
        description="Archive (true) or unarchive (false) the board",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Unchanged", "Archive", "Unarchive"],
            "x-enum-searchable": True,
        },
    )


class TrelloDeleteBoardConfig(BaseModel):
    """Permanently delete a board."""

    operation: Literal["delete_board"] = Field(
        "delete_board",
        json_schema_extra={
            "const": "delete_board",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Delete Board",
        },
        title="Delete Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to permanently delete",
        json_schema_extra={
            "x-resource-type": "trello_board",
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste board ID",
            }
        },
    )


class TrelloGetBoardListsConfig(BaseModel):
    """Get all lists (columns) on a board."""

    operation: Literal["get_board_lists"] = Field(
        "get_board_lists",
        json_schema_extra={
            "const": "get_board_lists",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Get Lists on a Board",
        },
        title="Get Lists on a Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board whose lists to retrieve",
        json_schema_extra={
            "x-resource-type": "trello_board",
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste board ID",
            }
        },
    )


class TrelloGetBoardCardsConfig(BaseModel):
    """Get all cards on a board."""

    operation: Literal["get_board_cards"] = Field(
        "get_board_cards",
        json_schema_extra={
            "const": "get_board_cards",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Get Cards on a Board",
        },
        title="Get Cards on a Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board whose cards to retrieve",
        json_schema_extra={
            "x-resource-type": "trello_board",
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste board ID",
            }
        },
    )


class TrelloGetBoardLabelsConfig(BaseModel):
    """List labels available on a board."""

    operation: Literal["get_board_labels"] = Field(
        "get_board_labels",
        json_schema_extra={
            "const": "get_board_labels",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Get Board Labels",
        },
        title="Get Board Labels",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board whose labels to retrieve",
        json_schema_extra={
            "x-resource-type": "trello_board",
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste board ID",
            }
        },
    )


class TrelloGetBoardMembersConfig(BaseModel):
    """List members of a board."""

    operation: Literal["get_board_members"] = Field(
        "get_board_members",
        json_schema_extra={
            "const": "get_board_members",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Get Board Members",
        },
        title="Get Board Members",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board whose members to retrieve",
        json_schema_extra={
            "x-resource-type": "trello_board",
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste board ID",
            }
        },
    )


class TrelloCreateListConfig(BaseModel):
    """Create a new list (column) on a board."""

    operation: Literal["create_list"] = Field(
        "create_list",
        json_schema_extra={
            "const": "create_list",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Create List",
        },
        title="Create List",
    )
    name: str = Field(..., title="Name", description="Name of the new list")
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to add the list to",
        json_schema_extra={
            "x-resource-type": "trello_board",
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste board ID",
            }
        },
    )
    pos: Optional[str] = Field(
        None, title="Position", description="Position: 'top', 'bottom', or a positive number"
    )


class TrelloGetListCardsConfig(BaseModel):
    """Get all cards within a list."""

    operation: Literal["get_list_cards"] = Field(
        "get_list_cards",
        json_schema_extra={
            "const": "get_list_cards",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Get Cards in a List",
        },
        title="Get Cards in a List",
    )
    list_id: str = Field(..., title="List ID", description="The list whose cards to retrieve")


class TrelloArchiveListConfig(BaseModel):
    """Archive or unarchive a list."""

    operation: Literal["archive_list"] = Field(
        "archive_list",
        json_schema_extra={
            "const": "archive_list",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Archive List",
        },
        title="Archive List",
    )
    list_id: str = Field(..., title="List ID", description="The list to archive or unarchive")
    value: str = Field(
        "true",
        title="Archived",
        description="Archive (true) or unarchive (false)",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Archive", "Unarchive"],
            "x-enum-searchable": True,
        },
    )


class TrelloMoveAllCardsConfig(BaseModel):
    """Move every card in a list to another list."""

    operation: Literal["move_all_cards"] = Field(
        "move_all_cards",
        json_schema_extra={
            "const": "move_all_cards",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Move All Cards in a List",
        },
        title="Move All Cards in a List",
    )
    list_id: str = Field(..., title="Source List ID", description="The list to move cards from")
    id_board: str = Field(
        ...,
        title="Destination Board",
        description="Board that the destination list belongs to",
        json_schema_extra={
            "x-resource-type": "trello_board",
            "x-dynamic-options": {
                "field_name": "id_board",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste board ID",
            }
        },
    )
    id_list: str = Field(..., title="Destination List ID", description="The list to move cards into")


class TrelloGetCardConfig(BaseModel):
    """Retrieve a single card."""

    operation: Literal["get_card"] = Field(
        "get_card",
        json_schema_extra={
            "const": "get_card",
            "ui:hidden": True,
            "x-category": "Cards",
            "x-is-trigger": False,
            "x-display-name": "Get Card",
        },
        title="Get Card",
    )
    card_id: str = Field(..., title="Card ID", description="The card to retrieve")


class TrelloCreateCardConfig(BaseModel):
    """Create a new card in a list."""

    operation: Literal["create_card"] = Field(
        "create_card",
        json_schema_extra={
            "const": "create_card",
            "ui:hidden": True,
            "x-category": "Cards",
            "x-is-trigger": False,
            "x-display-name": "Create Card",
        },
        title="Create Card",
    )
    id_list: str = Field(..., title="List ID", description="The list to add the card to")
    name: str = Field(..., title="Name", description="Card title")
    desc: Optional[str] = Field(
        None,
        title="Description",
        description="Card description (markdown)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    pos: Optional[str] = Field(
        None, title="Position", description="Position: 'top', 'bottom', or a positive number"
    )
    due: Optional[str] = Field(
        None, title="Due Date", description="Due date in ISO 8601 (e.g. 2026-07-01T17:00:00Z)"
    )
    id_members: Optional[str] = Field(
        None, title="Member IDs", description="Comma-separated member IDs to assign"
    )
    id_labels: Optional[str] = Field(
        None, title="Label IDs", description="Comma-separated label IDs to apply"
    )


class TrelloUpdateCardConfig(BaseModel):
    """Update a card (rename, move, set due date, archive)."""

    operation: Literal["update_card"] = Field(
        "update_card",
        json_schema_extra={
            "const": "update_card",
            "ui:hidden": True,
            "x-category": "Cards",
            "x-is-trigger": False,
            "x-display-name": "Update Card",
        },
        title="Update Card",
    )
    card_id: str = Field(..., title="Card ID", description="The card to update")
    name: Optional[str] = Field(None, title="Name", description="New card title")
    desc: Optional[str] = Field(
        None,
        title="Description",
        description="New card description",
        json_schema_extra={"ui:widget": "textarea"},
    )
    id_list: Optional[str] = Field(
        None, title="Move to List ID", description="Move the card to this list"
    )
    due: Optional[str] = Field(
        None, title="Due Date", description="New due date in ISO 8601"
    )
    closed: Optional[str] = Field(
        None,
        title="Closed",
        description="Archive (true) or unarchive (false) the card",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Unchanged", "Archive", "Unarchive"],
            "x-enum-searchable": True,
        },
    )


class TrelloDeleteCardConfig(BaseModel):
    """Permanently delete a card."""

    operation: Literal["delete_card"] = Field(
        "delete_card",
        json_schema_extra={
            "const": "delete_card",
            "ui:hidden": True,
            "x-category": "Cards",
            "x-is-trigger": False,
            "x-display-name": "Delete Card",
        },
        title="Delete Card",
    )
    card_id: str = Field(..., title="Card ID", description="The card to permanently delete")


class TrelloAddCommentConfig(BaseModel):
    """Post a comment on a card."""

    operation: Literal["add_comment"] = Field(
        "add_comment",
        json_schema_extra={
            "const": "add_comment",
            "ui:hidden": True,
            "x-category": "Cards",
            "x-is-trigger": False,
            "x-display-name": "Add Comment to Card",
        },
        title="Add Comment to Card",
    )
    card_id: str = Field(..., title="Card ID", description="The card to comment on")
    text: str = Field(
        ...,
        title="Comment",
        description="Comment text (markdown)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class TrelloAddAttachmentConfig(BaseModel):
    """Attach a URL to a card."""

    operation: Literal["add_attachment"] = Field(
        "add_attachment",
        json_schema_extra={
            "const": "add_attachment",
            "ui:hidden": True,
            "x-category": "Cards",
            "x-is-trigger": False,
            "x-display-name": "Add Attachment to Card",
        },
        title="Add Attachment to Card",
    )
    card_id: str = Field(..., title="Card ID", description="The card to attach to")
    url: str = Field(..., title="URL", description="URL of the attachment", json_schema_extra={"format": "uri"})
    name: Optional[str] = Field(None, title="Name", description="Display name for the attachment")


class TrelloAddMemberConfig(BaseModel):
    """Assign a member to a card."""

    operation: Literal["add_member"] = Field(
        "add_member",
        json_schema_extra={
            "const": "add_member",
            "ui:hidden": True,
            "x-category": "Cards",
            "x-is-trigger": False,
            "x-display-name": "Add Member to Card",
        },
        title="Add Member to Card",
    )
    card_id: str = Field(..., title="Card ID", description="The card to assign a member to")
    value: str = Field(..., title="Member ID", description="ID of the member to assign")


class TrelloRemoveMemberConfig(BaseModel):
    """Unassign a member from a card."""

    operation: Literal["remove_member"] = Field(
        "remove_member",
        json_schema_extra={
            "const": "remove_member",
            "ui:hidden": True,
            "x-category": "Cards",
            "x-is-trigger": False,
            "x-display-name": "Remove Member from Card",
        },
        title="Remove Member from Card",
    )
    card_id: str = Field(..., title="Card ID", description="The card to unassign from")
    id_member: str = Field(..., title="Member ID", description="ID of the member to remove")


class TrelloAddLabelConfig(BaseModel):
    """Add an existing label to a card."""

    operation: Literal["add_label"] = Field(
        "add_label",
        json_schema_extra={
            "const": "add_label",
            "ui:hidden": True,
            "x-category": "Cards",
            "x-is-trigger": False,
            "x-display-name": "Add Label to Card",
        },
        title="Add Label to Card",
    )
    card_id: str = Field(..., title="Card ID", description="The card to label")
    value: str = Field(..., title="Label ID", description="ID of the label to add")


class TrelloRemoveLabelConfig(BaseModel):
    """Remove a label from a card."""

    operation: Literal["remove_label"] = Field(
        "remove_label",
        json_schema_extra={
            "const": "remove_label",
            "ui:hidden": True,
            "x-category": "Cards",
            "x-is-trigger": False,
            "x-display-name": "Remove Label from Card",
        },
        title="Remove Label from Card",
    )
    card_id: str = Field(..., title="Card ID", description="The card to remove the label from")
    id_label: str = Field(..., title="Label ID", description="ID of the label to remove")


class TrelloCreateChecklistConfig(BaseModel):
    """Add a checklist to a card."""

    operation: Literal["create_checklist"] = Field(
        "create_checklist",
        json_schema_extra={
            "const": "create_checklist",
            "ui:hidden": True,
            "x-category": "Checklists",
            "x-is-trigger": False,
            "x-display-name": "Create Checklist on Card",
        },
        title="Create Checklist on Card",
    )
    card_id: str = Field(..., title="Card ID", description="The card to add a checklist to")
    name: str = Field(..., title="Name", description="Name of the checklist")


class TrelloAddChecklistItemConfig(BaseModel):
    """Add an item to a checklist."""

    operation: Literal["add_checklist_item"] = Field(
        "add_checklist_item",
        json_schema_extra={
            "const": "add_checklist_item",
            "ui:hidden": True,
            "x-category": "Checklists",
            "x-is-trigger": False,
            "x-display-name": "Add Checklist Item",
        },
        title="Add Checklist Item",
    )
    checklist_id: str = Field(..., title="Checklist ID", description="The checklist to add an item to")
    name: str = Field(..., title="Item", description="Text of the checklist item")
    checked: Optional[str] = Field(
        "false",
        title="Checked",
        description="Whether the item starts checked",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )


class TrelloUpdateListConfig(BaseModel):
    """Rename or modify a list."""

    operation: Literal["update_list"] = Field(
        "update_list",
        json_schema_extra={
            "const": "update_list",
            "ui:hidden": True,
            "x-category": "Lists",
            "x-is-trigger": False,
            "x-display-name": "Update List",
        },
        title="Update List",
    )
    list_id: str = Field(..., title="List ID", description="The list to update")
    name: Optional[str] = Field(None, title="Name", description="New name for the list")
    pos: Optional[str] = Field(
        None, title="Position", description="New position: 'top', 'bottom', or a positive number"
    )
    subscribed: Optional[str] = Field(
        None,
        title="Subscribed",
        description="Subscribe (true) or unsubscribe (false) from the list",
        json_schema_extra={
            "enum": ["", "true", "false"],
            "enumNames": ["Unchanged", "Subscribe", "Unsubscribe"],
            "x-enum-searchable": True,
        },
    )


class TrelloGetCardChecklistsConfig(BaseModel):
    """Get all checklists on a card."""

    operation: Literal["get_card_checklists"] = Field(
        "get_card_checklists",
        json_schema_extra={
            "const": "get_card_checklists",
            "ui:hidden": True,
            "x-category": "Checklists",
            "x-is-trigger": False,
            "x-display-name": "Get Card Checklists",
        },
        title="Get Card Checklists",
    )
    card_id: str = Field(..., title="Card ID", description="The card whose checklists to retrieve")


class TrelloUpdateChecklistItemConfig(BaseModel):
    """Check or uncheck a checklist item (check item state)."""

    operation: Literal["update_checklist_item"] = Field(
        "update_checklist_item",
        json_schema_extra={
            "const": "update_checklist_item",
            "ui:hidden": True,
            "x-category": "Checklists",
            "x-is-trigger": False,
            "x-display-name": "Update Checklist Item",
        },
        title="Update Checklist Item",
    )
    card_id: str = Field(..., title="Card ID", description="The card that owns the checklist item")
    check_item_id: str = Field(..., title="Check Item ID", description="The checklist item to update")
    state: Optional[str] = Field(
        None,
        title="State",
        description="Mark the item complete or incomplete",
        json_schema_extra={
            "enum": ["", "complete", "incomplete"],
            "enumNames": ["Unchanged", "Complete", "Incomplete"],
            "x-enum-searchable": True,
        },
    )
    name: Optional[str] = Field(None, title="Name", description="New text for the checklist item")


class TrelloDeleteChecklistConfig(BaseModel):
    """Delete a checklist from a card."""

    operation: Literal["delete_checklist"] = Field(
        "delete_checklist",
        json_schema_extra={
            "const": "delete_checklist",
            "ui:hidden": True,
            "x-category": "Checklists",
            "x-is-trigger": False,
            "x-display-name": "Delete Checklist",
        },
        title="Delete Checklist",
    )
    checklist_id: str = Field(..., title="Checklist ID", description="The checklist to delete")


class TrelloDeleteChecklistItemConfig(BaseModel):
    """Delete an item from a checklist."""

    operation: Literal["delete_checklist_item"] = Field(
        "delete_checklist_item",
        json_schema_extra={
            "const": "delete_checklist_item",
            "ui:hidden": True,
            "x-category": "Checklists",
            "x-is-trigger": False,
            "x-display-name": "Delete Checklist Item",
        },
        title="Delete Checklist Item",
    )
    checklist_id: str = Field(..., title="Checklist ID", description="The checklist containing the item")
    check_item_id: str = Field(..., title="Check Item ID", description="The checklist item to delete")


class TrelloCreateLabelConfig(BaseModel):
    """Create a new label on a board."""

    operation: Literal["create_label"] = Field(
        "create_label",
        json_schema_extra={
            "const": "create_label",
            "ui:hidden": True,
            "x-category": "Labels",
            "x-is-trigger": False,
            "x-display-name": "Create Label",
        },
        title="Create Label",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to create the label on",
        json_schema_extra={
            "x-resource-type": "trello_board",
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste board ID",
            }
        },
    )
    name: str = Field(..., title="Name", description="Name of the label")
    color: Optional[str] = Field(
        None,
        title="Color",
        description="Label color",
        json_schema_extra={
            "enum": ["", "green", "yellow", "orange", "red", "purple", "blue", "sky", "lime", "pink", "black"],
            "enumNames": ["None", "Green", "Yellow", "Orange", "Red", "Purple", "Blue", "Sky", "Lime", "Pink", "Black"],
            "x-enum-searchable": True,
        },
    )


class TrelloUpdateLabelConfig(BaseModel):
    """Rename or recolor a board label."""

    operation: Literal["update_label"] = Field(
        "update_label",
        json_schema_extra={
            "const": "update_label",
            "ui:hidden": True,
            "x-category": "Labels",
            "x-is-trigger": False,
            "x-display-name": "Update Label",
        },
        title="Update Label",
    )
    label_id: str = Field(..., title="Label ID", description="The label to update")
    name: Optional[str] = Field(None, title="Name", description="New name for the label")
    color: Optional[str] = Field(
        None,
        title="Color",
        description="New label color",
        json_schema_extra={
            "enum": ["", "green", "yellow", "orange", "red", "purple", "blue", "sky", "lime", "pink", "black"],
            "enumNames": ["None", "Green", "Yellow", "Orange", "Red", "Purple", "Blue", "Sky", "Lime", "Pink", "Black"],
            "x-enum-searchable": True,
        },
    )


class TrelloDeleteLabelConfig(BaseModel):
    """Delete a label from a board."""

    operation: Literal["delete_label"] = Field(
        "delete_label",
        json_schema_extra={
            "const": "delete_label",
            "ui:hidden": True,
            "x-category": "Labels",
            "x-is-trigger": False,
            "x-display-name": "Delete Label",
        },
        title="Delete Label",
    )
    label_id: str = Field(..., title="Label ID", description="The label to delete")


class TrelloGetMemberCardsConfig(BaseModel):
    """Get all cards assigned to a member."""

    operation: Literal["get_member_cards"] = Field(
        "get_member_cards",
        json_schema_extra={
            "const": "get_member_cards",
            "ui:hidden": True,
            "x-category": "Members",
            "x-is-trigger": False,
            "x-display-name": "Get Member's Cards",
        },
        title="Get Member's Cards",
    )
    member_id: str = Field(
        "me", title="Member ID", description="Member ID or 'me' for the current user"
    )


class TrelloAddMemberToBoardConfig(BaseModel):
    """Add or update a member's role on a board."""

    operation: Literal["add_member_to_board"] = Field(
        "add_member_to_board",
        json_schema_extra={
            "const": "add_member_to_board",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Add Member to Board",
        },
        title="Add Member to Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to add the member to",
        json_schema_extra={
            "x-resource-type": "trello_board",
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste board ID",
            }
        },
    )
    id_member: str = Field(..., title="Member ID", description="ID or username of the member to add")
    member_type: str = Field(
        "normal",
        title="Role",
        description="Member role on the board",
        json_schema_extra={
            "enum": ["admin", "normal", "observer"],
            "enumNames": ["Admin", "Normal", "Observer"],
            "x-enum-searchable": True,
        },
    )


class TrelloRemoveMemberFromBoardConfig(BaseModel):
    """Remove a member from a board."""

    operation: Literal["remove_member_from_board"] = Field(
        "remove_member_from_board",
        json_schema_extra={
            "const": "remove_member_from_board",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Remove Member from Board",
        },
        title="Remove Member from Board",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to remove the member from",
        json_schema_extra={
            "x-resource-type": "trello_board",
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste board ID",
            }
        },
    )
    id_member: str = Field(..., title="Member ID", description="ID of the member to remove")


class TrelloGetCardActionsConfig(BaseModel):
    """Get the activity feed (actions) for a card."""

    operation: Literal["get_card_actions"] = Field(
        "get_card_actions",
        json_schema_extra={
            "const": "get_card_actions",
            "ui:hidden": True,
            "x-category": "Cards",
            "x-is-trigger": False,
            "x-display-name": "Get Card Actions",
        },
        title="Get Card Actions",
    )
    card_id: str = Field(..., title="Card ID", description="The card whose actions to retrieve")
    filter: Optional[str] = Field(
        None,
        title="Filter",
        description="Comma-separated action types to include (e.g. commentCard,updateCard). Leave blank for all.",
    )


class TrelloGetBoardActionsConfig(BaseModel):
    """Get the activity feed (actions) for a board."""

    operation: Literal["get_board_actions"] = Field(
        "get_board_actions",
        json_schema_extra={
            "const": "get_board_actions",
            "ui:hidden": True,
            "x-category": "Boards",
            "x-is-trigger": False,
            "x-display-name": "Get Board Actions",
        },
        title="Get Board Actions",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board whose actions to retrieve",
        json_schema_extra={
            "x-resource-type": "trello_board",
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste board ID",
            }
        },
    )
    filter: Optional[str] = Field(
        None,
        title="Filter",
        description="Comma-separated action types to include (e.g. createCard,commentCard). Leave blank for all.",
    )


# ============================================================================
# Webhook Trigger Configs
# ============================================================================

class TrelloBoardChangeTriggerConfig(BaseModel):
    """Fire the workflow when anything changes on a Trello board.

    Watches the entire board model — fires on card creation/updates/comments,
    list changes, board membership changes, and more. Use On Card Change instead
    if you only care about a specific card.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_board_change"] = Field(
        "on_board_change",
        json_schema_extra={
            "const": "on_board_change",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Board Change",
        },
        title="On Board Change",
    )
    board_id: str = Field(
        ...,
        title="Board",
        description="The board to watch for changes",
        json_schema_extra={
            "x-resource-type": "trello_board",
            "x-dynamic-options": {
                "field_name": "board_id",
                "placeholder": "Select a board...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste board ID",
            }
        },
    )
    event_types: str = Field(
        "*",
        title="Trigger On",
        description=(
            "Which event fires the workflow. Trello delivers every board change "
            "to this webhook; this filters by the payload's action.type. "
            "Choose 'Any change on the board' to fire on everything."
        ),
        json_schema_extra={
            "enum": TRELLO_BOARD_EVENTS,
            "enumNames": TRELLO_BOARD_EVENT_LABELS,
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Trello posts board changes here. Registered automatically when you connect credentials.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    callback_url: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class TrelloCardChangeTriggerConfig(BaseModel):
    """Fire the workflow when a specific Trello card changes.

    Watches a single card model — fires only on changes to that card (comments,
    member assignments, checklist updates, etc.). Use On Board Change instead
    if you want to react to any card activity on a board.
    """

    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})

    operation: Literal["on_card_change"] = Field(
        "on_card_change",
        json_schema_extra={
            "const": "on_card_change",
            "ui:hidden": True,
            "x-category": None,
            "x-is-trigger": True,
            "x-display-name": "On Card Change",
        },
        title="On Card Change",
    )
    card_id: str = Field(
        ...,
        title="Card ID",
        description="ID of the specific Trello card to watch for changes",
    )
    event_types: str = Field(
        "*",
        title="Trigger On",
        description=(
            "Which card event fires the workflow. Trello delivers all card changes "
            "to this webhook; this filters by the payload's action.type."
        ),
        json_schema_extra={
            "enum": TRELLO_CARD_EVENTS,
            "enumNames": TRELLO_CARD_EVENT_LABELS,
            "x-enum-searchable": True,
        },
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Webhook URL",
        description="Trello posts card changes here. Registered automatically when you connect credentials.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )
    webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    external_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    signing_secret: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    callback_url: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    relay_connected: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    is_production: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_registered: Optional[bool] = Field(default=None, json_schema_extra={"ui:hidden": True})
    trigger_error: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})



# ============================================================================
# Discriminated Union
# ============================================================================


TrelloConfig = Annotated[
    Union[
        TrelloSearchConfig,
        TrelloGetMeConfig,
        TrelloGetMemberBoardsConfig,
        TrelloGetMemberCardsConfig,
        TrelloGetBoardConfig,
        TrelloCreateBoardConfig,
        TrelloUpdateBoardConfig,
        TrelloDeleteBoardConfig,
        TrelloGetBoardListsConfig,
        TrelloGetBoardCardsConfig,
        TrelloGetBoardLabelsConfig,
        TrelloGetBoardMembersConfig,
        TrelloGetBoardActionsConfig,
        TrelloAddMemberToBoardConfig,
        TrelloRemoveMemberFromBoardConfig,
        TrelloCreateListConfig,
        TrelloUpdateListConfig,
        TrelloGetListCardsConfig,
        TrelloArchiveListConfig,
        TrelloMoveAllCardsConfig,
        TrelloGetCardConfig,
        TrelloCreateCardConfig,
        TrelloUpdateCardConfig,
        TrelloDeleteCardConfig,
        TrelloAddCommentConfig,
        TrelloAddAttachmentConfig,
        TrelloAddMemberConfig,
        TrelloRemoveMemberConfig,
        TrelloAddLabelConfig,
        TrelloRemoveLabelConfig,
        TrelloGetCardActionsConfig,
        TrelloGetCardChecklistsConfig,
        TrelloCreateChecklistConfig,
        TrelloAddChecklistItemConfig,
        TrelloUpdateChecklistItemConfig,
        TrelloDeleteChecklistConfig,
        TrelloDeleteChecklistItemConfig,
        TrelloCreateLabelConfig,
        TrelloUpdateLabelConfig,
        TrelloDeleteLabelConfig,
        TrelloBoardChangeTriggerConfig,
        TrelloCardChangeTriggerConfig,
    ],
    Discriminator("operation"),
]


class TrelloNodeConfig(NodeConfig[TrelloConfig, TrelloCredential]):
    """Full configuration for the Trello node including credentials."""

    pass


# ============================================================================
# Node Implementation
# ============================================================================


def _comma_list(value: Optional[str]) -> Optional[str]:
    """Normalize a comma-separated string, dropping empties; None if empty."""
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return ",".join(parts) if parts else None


async def _trello_request(
    api_key: str,
    api_token: str,
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    action_name: str = "request",
) -> Dict[str, Any]:
    """Make an authenticated Trello v1 request and return a structured result.

    Trello takes `key` and `token` as query params; all other inputs (including
    mutations) are also passed as query params per the REST API convention.
    """
    url = f"{TRELLO_API_BASE}{endpoint}"
    query: Dict[str, Any] = {"key": api_key, "token": api_token}
    if params:
        query.update({k: v for k, v in params.items() if v not in (None, "")})

    start = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(method=method, url=url, params=query)
            api_ms = round((time.time() - start) * 1000, 2)
            if response.status_code >= 400:
                try:
                    err = response.json()
                    message = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                except Exception:
                    message = response.text
                if isinstance(message, str):
                    message = message.encode("ascii", errors="replace").decode("ascii")
                logger.error(f"[TrelloNode] API error ({action_name}): {message}")
                return {
                    "status": "error",
                    "action": action_name,
                    "error": message,
                    "status_code": response.status_code,
                    "timing_ms": {"api_request": api_ms},
                }
            try:
                data: Any = response.json()
            except Exception:
                data = {"raw": response.text}
            return {
                "status": "success",
                "action": action_name,
                "data": data,
                "status_code": response.status_code,
                "timing_ms": {"api_request": api_ms},
            }
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": action_name,
                "error": "Request timed out",
                "status_code": 408,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }
        except Exception as e:
            msg = str(e).encode("ascii", errors="replace").decode("ascii")
            logger.error(f"[TrelloNode] Request failed ({action_name}): {msg}")
            return {
                "status": "error",
                "action": action_name,
                "error": msg,
                "status_code": 500,
                "timing_ms": {"api_request": round((time.time() - start) * 1000, 2)},
            }


class TrelloNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Trello project-management automation node."""

    edit_examples = [
        "Create a card in the To Do list when a form is submitted",
        "Add a comment to a Trello card when a deal closes",
        "Move all cards from Doing to Done at the end of a sprint",
        "List every card on a board for a weekly status report",
        "Trigger a workflow whenever a card on a board changes",
    ]

    @classmethod
    def get_config_model(cls):
        return TrelloNodeConfig

    # ------------------------------------------------------------------
    # Dynamic options (boards)
    # ------------------------------------------------------------------
    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name not in ("board_id", "id_board"):
            return {"options": []}
        if not credential_data:
            return {"options": []}
        api_key = credential_data.get("api_key")
        api_token = credential_data.get("api_token")
        result = await _trello_request(
            api_key,
            api_token,
            "GET",
            "/members/me/boards",
            params={"fields": "name,closed"},
            action_name="list_boards",
        )
        if result.get("status") != "success":
            return {"options": []}
        boards = result.get("data") or []
        options = []
        for board in boards:
            if not isinstance(board, dict) or board.get("closed"):
                continue
            board_id = board.get("id")
            name = board.get("name") or f"Board {board_id}"
            if board_id:
                options.append({"label": str(name), "value": str(board_id)})
        return {"options": options}

    # ------------------------------------------------------------------
    # Webhook trigger registration
    # ------------------------------------------------------------------
    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "board_id": (config or {}).get("board_id"),
            "card_id": (config or {}).get("card_id"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Optional[Dict[str, Any]]:
        api_key = credential.get("api_key")
        api_token = credential.get("api_token")
        if not api_key or not api_token:
            raise ValueError("A Trello API key and token are required to register the trigger")
        cfg = config or {}
        id_model = cfg.get("board_id") or cfg.get("card_id")
        if not id_model:
            raise ValueError("A board or card ID is required for the Trello trigger")
        # Trello's create-webhook API has no event filter — a webhook delivers
        # every change to the model. The user's event_types selection is applied
        # at delivery time in filter_trigger_payload; nothing to pass here.
        result = await _trello_request(
            api_key,
            api_token,
            "POST",
            f"/tokens/{api_token}/webhooks/",
            params={
                "callbackURL": webhook_url,
                "idModel": id_model,
                "description": f"NoClick trigger {node_id}",
            },
            action_name="register_webhook",
        )
        if result.get("status") != "success":
            raise ValueError(f"Trello webhook registration failed: {result.get('error')}")
        data = result.get("data") or {}
        external_id = data.get("id") if isinstance(data, dict) else None
        # Trello signs callbacks with the app's API secret + callbackURL; store both
        # so verify_webhook_signature can reconstruct the HMAC.
        return {
            "external_webhook_id": str(external_id) if external_id else None,
            "signing_secret": credential.get("api_secret"),
            "callback_url": webhook_url,
        }

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        external_id = (config or {}).get("external_webhook_id")
        api_key = (credential or {}).get("api_key")
        api_token = (credential or {}).get("api_token")
        if not external_id or not api_key or not api_token:
            return
        await _trello_request(
            api_key,
            api_token,
            "DELETE",
            f"/webhooks/{external_id}",
            action_name="unregister_webhook",
        )

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        secret = (config or {}).get("signing_secret")
        callback_url = (config or {}).get("callback_url")
        if not secret or not callback_url:
            return True  # no app secret stored — accept (signature verification not armed)
        sent = headers.get("x-trello-webhook")
        if not sent:
            return False
        # Trello: base64(HMAC-SHA1(request_body + callbackURL, api_secret))
        digest = hmac.new(secret.encode(), body + callback_url.encode(), hashlib.sha1).digest()
        expected = base64.b64encode(digest).decode()
        return hmac.compare_digest(expected, sent)

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Skip deliveries whose action.type isn't the selected event.

        Trello registers a single webhook per model and POSTs every change to it
        (no per-subscription event filter), so the user's event choice is applied
        here at delivery time. "*" (the default) accepts everything.
        """
        selected = (config or {}).get("event_types") or "*"
        if selected == "*":
            return True
        action_type = ((payload or {}).get("action") or {}).get("type")
        return action_type == selected

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        start_time = time.time()
        config = self.config
        if not config or not isinstance(config, TrelloNodeConfig):
            raise ValueError("Valid configuration is required")
        op = config.config

        if isinstance(op, TrelloBoardChangeTriggerConfig):
            return {
                "status": "success",
                "action": "on_board_change",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        if isinstance(op, TrelloCardChangeTriggerConfig):
            return {
                "status": "success",
                "action": "on_card_change",
                "data": {**inputs, "webhook_url": op.webhook_url},
                "timing_ms": {"total": round((time.time() - start_time) * 1000, 2)},
            }

        credentials = config.credentials
        if not credentials:
            raise ValueError("Credentials are required. Add your Trello API key and token.")
        api_key = credentials.api_key
        api_token = credentials.api_token

        handlers = {
            "search": self._search,
            "get_me": self._get_me,
            "get_member_boards": self._get_member_boards,
            "get_member_cards": self._get_member_cards,
            "get_board": self._get_board,
            "create_board": self._create_board,
            "update_board": self._update_board,
            "delete_board": self._delete_board,
            "get_board_lists": self._get_board_lists,
            "get_board_cards": self._get_board_cards,
            "get_board_labels": self._get_board_labels,
            "get_board_members": self._get_board_members,
            "get_board_actions": self._get_board_actions,
            "add_member_to_board": self._add_member_to_board,
            "remove_member_from_board": self._remove_member_from_board,
            "create_list": self._create_list,
            "update_list": self._update_list,
            "get_list_cards": self._get_list_cards,
            "archive_list": self._archive_list,
            "move_all_cards": self._move_all_cards,
            "get_card": self._get_card,
            "create_card": self._create_card,
            "update_card": self._update_card,
            "delete_card": self._delete_card,
            "add_comment": self._add_comment,
            "add_attachment": self._add_attachment,
            "add_member": self._add_member,
            "remove_member": self._remove_member,
            "add_label": self._add_label,
            "remove_label": self._remove_label,
            "get_card_actions": self._get_card_actions,
            "get_card_checklists": self._get_card_checklists,
            "create_checklist": self._create_checklist,
            "add_checklist_item": self._add_checklist_item,
            "update_checklist_item": self._update_checklist_item,
            "delete_checklist": self._delete_checklist,
            "delete_checklist_item": self._delete_checklist_item,
            "create_label": self._create_label,
            "update_label": self._update_label,
            "delete_label": self._delete_label,
        }
        handler = handlers.get(op.operation)
        if not handler:
            raise ValueError(f"Unknown operation: {op.operation}")

        result = await handler(op, api_key, api_token)
        result["timing_ms"] = {
            **result.get("timing_ms", {}),
            "total": round((time.time() - start_time) * 1000, 2),
        }
        return result

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def _search(self, c: TrelloSearchConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "GET", "/search",
            params={"query": c.query, "modelTypes": c.model_types or "all"},
            action_name="search",
        )

    async def _get_me(self, c: TrelloGetMeConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(key, token, "GET", "/members/me", action_name="get_me")

    async def _get_member_boards(self, c: TrelloGetMemberBoardsConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "GET", f"/members/{c.member_id}/boards", action_name="get_member_boards"
        )

    async def _get_board(self, c: TrelloGetBoardConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "GET", f"/boards/{c.board_id}", action_name="get_board"
        )

    async def _create_board(self, c: TrelloCreateBoardConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "POST", "/boards/",
            params={
                "name": c.name,
                "idOrganization": c.id_organization,
                "defaultLists": c.default_lists,
            },
            action_name="create_board",
        )

    async def _update_board(self, c: TrelloUpdateBoardConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "PUT", f"/boards/{c.board_id}",
            params={"name": c.name, "desc": c.desc, "closed": c.closed},
            action_name="update_board",
        )

    async def _delete_board(self, c: TrelloDeleteBoardConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "DELETE", f"/boards/{c.board_id}", action_name="delete_board"
        )

    async def _get_board_lists(self, c: TrelloGetBoardListsConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "GET", f"/boards/{c.board_id}/lists", action_name="get_board_lists"
        )

    async def _get_board_cards(self, c: TrelloGetBoardCardsConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "GET", f"/boards/{c.board_id}/cards", action_name="get_board_cards"
        )

    async def _get_board_labels(self, c: TrelloGetBoardLabelsConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "GET", f"/boards/{c.board_id}/labels", action_name="get_board_labels"
        )

    async def _get_board_members(self, c: TrelloGetBoardMembersConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "GET", f"/boards/{c.board_id}/members", action_name="get_board_members"
        )

    async def _create_list(self, c: TrelloCreateListConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "POST", "/lists",
            params={"name": c.name, "idBoard": c.board_id, "pos": c.pos},
            action_name="create_list",
        )

    async def _get_list_cards(self, c: TrelloGetListCardsConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "GET", f"/lists/{c.list_id}/cards", action_name="get_list_cards"
        )

    async def _archive_list(self, c: TrelloArchiveListConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "PUT", f"/lists/{c.list_id}/closed",
            params={"value": c.value}, action_name="archive_list",
        )

    async def _move_all_cards(self, c: TrelloMoveAllCardsConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "POST", f"/lists/{c.list_id}/moveAllCards",
            params={"idBoard": c.id_board, "idList": c.id_list},
            action_name="move_all_cards",
        )

    async def _get_card(self, c: TrelloGetCardConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "GET", f"/cards/{c.card_id}", action_name="get_card"
        )

    async def _create_card(self, c: TrelloCreateCardConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "POST", "/cards",
            params={
                "idList": c.id_list,
                "name": c.name,
                "desc": c.desc,
                "pos": c.pos,
                "due": c.due,
                "idMembers": _comma_list(c.id_members),
                "idLabels": _comma_list(c.id_labels),
            },
            action_name="create_card",
        )

    async def _update_card(self, c: TrelloUpdateCardConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "PUT", f"/cards/{c.card_id}",
            params={
                "name": c.name,
                "desc": c.desc,
                "idList": c.id_list,
                "due": c.due,
                "closed": c.closed,
            },
            action_name="update_card",
        )

    async def _delete_card(self, c: TrelloDeleteCardConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "DELETE", f"/cards/{c.card_id}", action_name="delete_card"
        )

    async def _add_comment(self, c: TrelloAddCommentConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "POST", f"/cards/{c.card_id}/actions/comments",
            params={"text": c.text}, action_name="add_comment",
        )

    async def _add_attachment(self, c: TrelloAddAttachmentConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "POST", f"/cards/{c.card_id}/attachments",
            params={"url": c.url, "name": c.name}, action_name="add_attachment",
        )

    async def _add_member(self, c: TrelloAddMemberConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "POST", f"/cards/{c.card_id}/idMembers",
            params={"value": c.value}, action_name="add_member",
        )

    async def _remove_member(self, c: TrelloRemoveMemberConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "DELETE", f"/cards/{c.card_id}/idMembers/{c.id_member}",
            action_name="remove_member",
        )

    async def _add_label(self, c: TrelloAddLabelConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "POST", f"/cards/{c.card_id}/idLabels",
            params={"value": c.value}, action_name="add_label",
        )

    async def _remove_label(self, c: TrelloRemoveLabelConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "DELETE", f"/cards/{c.card_id}/idLabels/{c.id_label}",
            action_name="remove_label",
        )

    async def _create_checklist(self, c: TrelloCreateChecklistConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "POST", f"/cards/{c.card_id}/checklists",
            params={"name": c.name}, action_name="create_checklist",
        )

    async def _add_checklist_item(self, c: TrelloAddChecklistItemConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "POST", f"/checklists/{c.checklist_id}/checkItems",
            params={"name": c.name, "checked": c.checked}, action_name="add_checklist_item",
        )

    async def _get_member_cards(self, c: TrelloGetMemberCardsConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "GET", f"/members/{c.member_id}/cards", action_name="get_member_cards"
        )

    async def _get_board_actions(self, c: TrelloGetBoardActionsConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "GET", f"/boards/{c.board_id}/actions",
            params={"filter": c.filter} if c.filter else None,
            action_name="get_board_actions",
        )

    async def _add_member_to_board(self, c: TrelloAddMemberToBoardConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "PUT", f"/boards/{c.board_id}/members/{c.id_member}",
            params={"type": c.member_type}, action_name="add_member_to_board",
        )

    async def _remove_member_from_board(self, c: TrelloRemoveMemberFromBoardConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "DELETE", f"/boards/{c.board_id}/members/{c.id_member}",
            action_name="remove_member_from_board",
        )

    async def _update_list(self, c: TrelloUpdateListConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "PUT", f"/lists/{c.list_id}",
            params={"name": c.name, "pos": c.pos, "subscribed": c.subscribed},
            action_name="update_list",
        )

    async def _get_card_actions(self, c: TrelloGetCardActionsConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "GET", f"/cards/{c.card_id}/actions",
            params={"filter": c.filter} if c.filter else None,
            action_name="get_card_actions",
        )

    async def _get_card_checklists(self, c: TrelloGetCardChecklistsConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "GET", f"/cards/{c.card_id}/checklists", action_name="get_card_checklists"
        )

    async def _update_checklist_item(self, c: TrelloUpdateChecklistItemConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "PUT", f"/cards/{c.card_id}/checkItem/{c.check_item_id}",
            params={"state": c.state, "name": c.name},
            action_name="update_checklist_item",
        )

    async def _delete_checklist(self, c: TrelloDeleteChecklistConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "DELETE", f"/checklists/{c.checklist_id}", action_name="delete_checklist"
        )

    async def _delete_checklist_item(self, c: TrelloDeleteChecklistItemConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "DELETE", f"/checklists/{c.checklist_id}/checkItems/{c.check_item_id}",
            action_name="delete_checklist_item",
        )

    async def _create_label(self, c: TrelloCreateLabelConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "POST", "/labels",
            params={"name": c.name, "color": c.color, "idBoard": c.board_id},
            action_name="create_label",
        )

    async def _update_label(self, c: TrelloUpdateLabelConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "PUT", f"/labels/{c.label_id}",
            params={"name": c.name, "color": c.color},
            action_name="update_label",
        )

    async def _delete_label(self, c: TrelloDeleteLabelConfig, key: str, token: str) -> Dict[str, Any]:
        return await _trello_request(
            key, token, "DELETE", f"/labels/{c.label_id}", action_name="delete_label"
        )
