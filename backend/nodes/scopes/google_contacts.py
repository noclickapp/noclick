"""Google Contacts → OAuth scope requirements (Google's shared scope notes are in google.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry
from nodes.scopes.google import _table


CONTACTS = "https://www.googleapis.com/auth/contacts"


# ---------------------------------------------------------------------------
# Contacts — People API v1, `people.*` and `contactGroups.*`.
# ---------------------------------------------------------------------------
# Only the user's own contacts are touched. `otherContacts.*` and the directory
# methods need scopes of their own (`contacts.other.readonly`,
# `directory.readonly`) and no operation calls them.
GOOGLE_CONTACTS_SCOPES = ScopeRegistry(
    provider="google-contacts",
    requirements=_table(
        {
            CONTACTS: (
                # contacts
                "list_contacts",
                "get_contact",
                "search_contacts",
                "create_contact",
                "update_contact",
                "delete_contact",
                # contact groups
                "list_contact_groups",
                "get_contact_group",
                "create_contact_group",
                "update_contact_group",
                "delete_contact_group",
            ),
        }
    ),
)
