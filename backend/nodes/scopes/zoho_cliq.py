"""Zoho Cliq v3 per-operation scopes from the published OpenAPI security entries.

Identity uses the Zoho Accounts profile read scope in addition to API scopes.
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement

ZOHO_CLIQ_SCOPES = ScopeRegistry(
    provider="zoho_cliq",
    requirements={
        "list_chats": ScopeRequirement(scopes=("ZohoCliq.Chats.READ",)),
        "get_chat": ScopeRequirement(scopes=("ZohoCliq.Chats.READ",)),
        "list_chat_members": ScopeRequirement(scopes=("ZohoCliq.Chats.READ",)),
        "create_chat": ScopeRequirement(scopes=("ZohoCliq.Chats.CREATE",)),
        "rename_chat": ScopeRequirement(scopes=("ZohoCliq.Chats.UPDATE",)),
        "add_chat_members": ScopeRequirement(scopes=("ZohoCliq.Chats.UPDATE",)),
        "leave_chat": ScopeRequirement(scopes=("ZohoCliq.Chats.UPDATE",)),
        "list_channels": ScopeRequirement(scopes=("ZohoCliq.Channels.READ",)),
        "get_channel": ScopeRequirement(scopes=("ZohoCliq.Channels.READ",)),
        "create_channel": ScopeRequirement(scopes=("ZohoCliq.Channels.CREATE",)),
        "update_channel": ScopeRequirement(scopes=("ZohoCliq.Channels.UPDATE",)),
        "list_channel_members": ScopeRequirement(scopes=("ZohoCliq.Channels.READ",)),
        "add_channel_members": ScopeRequirement(scopes=("ZohoCliq.Channels.UPDATE",)),
        "remove_channel_member": ScopeRequirement(scopes=("ZohoCliq.Channels.DELETE",)),
        "send_chat_message": ScopeRequirement(scopes=("ZohoCliq.Webhooks.CREATE",)),
        "send_channel_message": ScopeRequirement(scopes=("ZohoCliq.Webhooks.CREATE",)),
        "search_messages": ScopeRequirement(scopes=("ZohoCliq.Chats.READ",)),
        "edit_message": ScopeRequirement(scopes=("ZohoCliq.Messages.UPDATE",)),
    },
    extra_scopes={"default": ("aaaserver.profile.READ",)},
    enforcement=Enforcement.STRICT,
)
