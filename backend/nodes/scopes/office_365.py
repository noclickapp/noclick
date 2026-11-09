"""Delegated Microsoft Graph permissions for Office 365.

References: https://learn.microsoft.com/en-us/graph/permissions-reference
and the permissions tables in each operation's Graph v1.0 documentation.
ReadWrite permissions also cover the corresponding reads. Sending/replying
requires Mail.Send independently of Mail.ReadWrite.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

OFFICE_365_SCOPES = ScopeRegistry(
    provider="office-365",
    requirements={
        **{name: ScopeRequirement(scopes=("https://graph.microsoft.com/Mail.ReadWrite",))
           for name in ("list_messages", "get_message", "create_draft", "update_message",
                        "delete_message", "move_message", "list_mail_folders", "on_new_message")},
        **{name: ScopeRequirement(scopes=("https://graph.microsoft.com/Mail.Send",))
           for name in ("send_mail", "reply_message")},
        **{name: ScopeRequirement(scopes=("https://graph.microsoft.com/Calendars.ReadWrite",))
           for name in ("list_calendars", "list_events", "get_event", "create_event",
                        "update_event", "delete_event")},
        **{name: ScopeRequirement(scopes=("https://graph.microsoft.com/Contacts.ReadWrite",))
           for name in ("list_contacts", "get_contact", "create_contact",
                        "update_contact", "delete_contact")},
        "on_outlook_change": ScopeRequirement(scopes=("https://graph.microsoft.com/Mail.ReadWrite",
            "https://graph.microsoft.com/Calendars.ReadWrite", "https://graph.microsoft.com/Contacts.ReadWrite")),
        "get_profile": ScopeRequirement(scopes=("https://graph.microsoft.com/User.Read",)),
    },
    extra_scopes={"default": ("offline_access",)},
)
