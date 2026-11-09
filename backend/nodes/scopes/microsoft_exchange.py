"""Delegated Exchange Graph permissions.

https://learn.microsoft.com/en-us/graph/permissions-reference
Mail.Send covers send/reply/forward; Mail.ReadWrite covers drafts/folders and
message changes. Calendars.ReadWrite and Contacts.ReadWrite cover their CRUD.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

PREFIX = "https://graph.microsoft.com/"
EXCHANGE_SCOPES = ScopeRegistry(
    provider="microsoft",
    requirements={
        "list_messages": ScopeRequirement(scopes=(PREFIX + "Mail.ReadWrite",)),
        "get_message": ScopeRequirement(scopes=(PREFIX + "Mail.ReadWrite",)),
        "create_draft": ScopeRequirement(scopes=(PREFIX + "Mail.ReadWrite",)),
        "update_message": ScopeRequirement(scopes=(PREFIX + "Mail.ReadWrite",)),
        "delete_message": ScopeRequirement(scopes=(PREFIX + "Mail.ReadWrite",)),
        "move_message": ScopeRequirement(scopes=(PREFIX + "Mail.ReadWrite",)),
        "list_mail_folders": ScopeRequirement(scopes=(PREFIX + "Mail.ReadWrite",)),
        "get_mail_folder": ScopeRequirement(scopes=(PREFIX + "Mail.ReadWrite",)),
        "create_mail_folder": ScopeRequirement(scopes=(PREFIX + "Mail.ReadWrite",)),
        "send_email": ScopeRequirement(scopes=(PREFIX + "Mail.Send",)),
        "reply_message": ScopeRequirement(scopes=(PREFIX + "Mail.Send",)),
        "forward_message": ScopeRequirement(scopes=(PREFIX + "Mail.Send",)),
        "send_draft": ScopeRequirement(scopes=(PREFIX + "Mail.Send",)),
        "list_calendars": ScopeRequirement(scopes=(PREFIX + "Calendars.ReadWrite",)),
        "list_events": ScopeRequirement(scopes=(PREFIX + "Calendars.ReadWrite",)),
        "get_event": ScopeRequirement(scopes=(PREFIX + "Calendars.ReadWrite",)),
        "create_event": ScopeRequirement(scopes=(PREFIX + "Calendars.ReadWrite",)),
        "update_event": ScopeRequirement(scopes=(PREFIX + "Calendars.ReadWrite",)),
        "delete_event": ScopeRequirement(scopes=(PREFIX + "Calendars.ReadWrite",)),
        "list_contacts": ScopeRequirement(scopes=(PREFIX + "Contacts.ReadWrite",)),
        "get_contact": ScopeRequirement(scopes=(PREFIX + "Contacts.ReadWrite",)),
        "create_contact": ScopeRequirement(scopes=(PREFIX + "Contacts.ReadWrite",)),
        "update_contact": ScopeRequirement(scopes=(PREFIX + "Contacts.ReadWrite",)),
        "delete_contact": ScopeRequirement(scopes=(PREFIX + "Contacts.ReadWrite",)),
        "list_contact_folders": ScopeRequirement(scopes=(PREFIX + "Contacts.ReadWrite",)),
    },
    extra_scopes={"default": (PREFIX + "User.Read", "offline_access")},
)
