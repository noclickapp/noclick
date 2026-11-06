"""RingCentral app permissions from each operation's x-app-permission.

Source: https://netstorage.ringcentral.com/dpw/api-reference/specs/public/office/rc-platform.yml
These describe the permissions the pasted OAuth access token's app must have;
NoClick does not initiate OAuth or request a grant for this manual credential.
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement

RINGCENTRAL_SCOPES = ScopeRegistry(
    provider="ringcentral",
    requirements={
        "list_call_logs": ScopeRequirement(scopes=("ReadCallLog",)),
        "get_call_log": ScopeRequirement(scopes=("ReadCallLog",)),
        "list_active_calls": ScopeRequirement(scopes=("ReadCallLog",)),
        "create_ringout": ScopeRequirement(scopes=("RingOut",)),
        "get_ringout": ScopeRequirement(scopes=("RingOut",)),
        "cancel_ringout": ScopeRequirement(scopes=("RingOut",)),
        "send_fax": ScopeRequirement(scopes=("Faxes",)),
        "list_fax_cover_pages": ScopeRequirement(scopes=()),
        "list_messages": ScopeRequirement(scopes=("ReadMessages",)),
        "get_message": ScopeRequirement(scopes=("ReadMessages",)),
        "update_message": ScopeRequirement(scopes=("EditMessages",)),
        "delete_message": ScopeRequirement(scopes=("EditMessages",)),
        "send_sms": ScopeRequirement(scopes=("SMS",)),
        "list_phone_numbers": ScopeRequirement(scopes=("ReadAccounts",)),
        "get_extension": ScopeRequirement(scopes=("ReadAccounts",)),
        "list_contacts": ScopeRequirement(scopes=("ReadContacts",)),
        "create_contact": ScopeRequirement(scopes=("Contacts",)),
        "get_contact": ScopeRequirement(scopes=("ReadContacts",)),
        "update_contact": ScopeRequirement(scopes=("Contacts",)),
        "delete_contact": ScopeRequirement(scopes=("Contacts",)),
    },
    enforcement=Enforcement.STRICT,
)
