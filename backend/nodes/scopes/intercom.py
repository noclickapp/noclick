"""Intercom operation → OAuth permission requirements.

Intercom is the odd one out: its authorize endpoint takes **no ``scope``
parameter** (only ``client_id`` and ``state``). Permissions are fixed per app in
the Developer Hub, and Intercom's published permission list is human labels —
"Read conversations", "Write users and companies", "Read tickets" — with no
machine names anywhere in the docs. So ``x-oauth-scopes`` on this node is not a
request payload at all; it is the checklist a user must tick on their own app,
written in NoClick's own identifiers. This table maps each operation to the
identifier standing in for the documented label it needs, so the checklist can
be verified against the operations instead of trusted.

Because the identifiers are NoClick's, only the *label* side of each mapping is
verifiable, and only where Intercom names the resource explicitly. Endpoints
Intercom's permission list never mentions — Articles, data attributes, ticket
types, ``POST /messages``, Teams — are left unmapped rather than assigned a
label by resemblance. Two of those are real gaps in the checklist and are called
out with ``MISSING SCOPE``.

Webhook topics are permission-gated the same way: "Each Webhook topic is
associated with one or more permissions. When you set up a subscription to a
particular topic, you will need to select the appropriate permissions to be able
to receive a notification for that topic." The trigger operations therefore
carry the permission their topic family requires, even though NoClick never
calls an API to register them (the user adds the URL in the Developer Hub).

Enforcement is ``SUBSET``: nothing here may shrink the checklist.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- Contacts -- "Read and write users": list users, execute bulk actions,
    # and add or remove users from companies.
    "archive_contact": _s("read_write_users"),
    "create_contact": _s("read_write_users"),
    "create_note": _s("read_write_users"),
    "delete_contact": _s("read_write_users"),
    "get_contact": _s("read_write_users"),
    "list_contact_notes": _s("read_write_users"),
    "list_contacts": _s("read_write_users"),
    "merge_contacts": _s("read_write_users"),
    "search_contacts": _s("read_write_users"),
    "unarchive_contact": _s("read_write_users"),
    "update_contact": _s("read_write_users"),
    # Contact↔company edges touch both resources.
    "attach_contact_to_company": _s("read_write_users", "read_write_companies"),
    "detach_contact_from_company": _s("read_write_users", "read_write_companies"),
    "list_contact_companies": _s("read_write_users", "read_write_companies"),
    # "Write tags: create, update, use and delete tags" — tagging is a tag write
    # on a contact.
    "tag_contact": _s("read_write_tags", "read_write_users"),
    "untag_contact": _s("read_write_tags", "read_write_users"),

    # -- Companies -----------------------------------------------------------
    "create_company": _s("read_write_companies"),
    "delete_company": _s("read_write_companies"),
    "get_company": _s("read_write_companies"),
    "list_companies": _s("read_write_companies"),
    "list_company_contacts": _s("read_write_companies", "read_write_users"),
    # "Read and list users and companies" is documented as covering segments:
    # "List and view all segments, users, companies, and tags".
    "list_segments": _s("read_write_users", "read_write_companies"),

    # -- Conversations -- "Read conversations" / "Write conversations: reply to,
    # mark as read and close conversations".
    "create_conversation": _s("read_write_conversations"),
    "get_conversation": _s("read_write_conversations"),
    "list_conversations": _s("read_write_conversations"),
    "manage_conversation": _s("read_write_conversations"),
    "reply_conversation": _s("read_write_conversations"),
    "search_conversations": _s("read_write_conversations"),
    "tag_conversation": _s("read_write_tags", "read_write_conversations"),
    "untag_conversation": _s("read_write_tags", "read_write_conversations"),

    # -- Tickets -- "Read tickets: view tickets" / "Write tickets: create
    # tickets".
    "create_ticket": _s("read_write_tickets"),
    "get_ticket": _s("read_write_tickets"),
    "reply_ticket": _s("read_write_tickets"),
    "search_tickets": _s("read_write_tickets"),
    "update_ticket": _s("read_write_tickets"),

    # -- Tags -- "Read tags" / "Write tags".
    "create_tag": _s("read_write_tags"),
    "delete_tag": _s("read_write_tags"),
    "list_tags": _s("read_write_tags"),

    # -- Events -- "Write events: ability to submit events (i.e. user
    # activity)".
    "submit_event": _s("read_write_events"),

    # -- Workspace -- "Read admins: list and view all admins".
    "list_admins": _s("read_admins"),

    # -- Triggers. No API call registers these (the user pastes the URL into the
    # Developer Hub), but Intercom only delivers a topic to an app holding the
    # topic's permission.
    "on_company_event": _s("read_write_companies"),
    "on_contact_event": _s("read_write_users"),
    "on_conversation_event": _s("read_write_conversations"),
    "on_ticket_event": _s("read_write_tickets"),
}

INTERCOM_SCOPES = ScopeRegistry(
    provider="intercom",
    requirements=_REQUIREMENTS,
    unmapped=(
        # MISSING SCOPE: an Articles permission ("Read and List articles" /
        # "Read and Write Articles"). The Help Center operations hit
        # /articles, and nothing resembling an articles permission is on this
        # node's checklist, so an app configured from it cannot run them.
        "create_article",
        "delete_article",
        "get_article",
        "list_articles",
        "update_article",

        # MISSING SCOPE: a data-attributes permission ("Read content data:
        # access custom data attributes" / "Write data attributes"). Neither is
        # on the checklist, so GET /data_attributes has no permission behind it.
        "list_data_attributes",

        # Intercom's permission list names no Teams entry, so the checklist's
        # `read_teams` has no documented counterpart and GET /teams cannot be
        # tied to a verified permission. Possibly covered by "Read admins".
        "list_teams",

        # Intercom documents "Read tickets"/"Write tickets" for tickets, but
        # never mentions ticket TYPES; which permission GET /ticket_types needs
        # is unstated.
        "list_ticket_types",

        # POST /messages is not covered by any documented label — "Write
        # conversations" is scoped to "reply to, mark as read and close
        # conversations", which is not creating an outbound message.
        "send_message",
    ),
)
