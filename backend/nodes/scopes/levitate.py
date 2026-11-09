"""All Public API v1 resources require levitate:contacts.

Source: https://help.levitate.ai/article/735-levitate-public-api#scopes
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

LEVITATE_SCOPES = ScopeRegistry(
    provider="levitate",
    requirements={
        "get_company": ScopeRequirement(scopes=("levitate:contacts",)),
        "update_company": ScopeRequirement(scopes=("levitate:contacts",)),
        "delete_company": ScopeRequirement(scopes=("levitate:contacts",)),
        "list_companies": ScopeRequirement(scopes=("levitate:contacts",)),
        "create_company": ScopeRequirement(scopes=("levitate:contacts",)),
        "get_contact": ScopeRequirement(scopes=("levitate:contacts",)),
        "update_contact": ScopeRequirement(scopes=("levitate:contacts",)),
        "list_contacts": ScopeRequirement(scopes=("levitate:contacts",)),
        "create_contact": ScopeRequirement(scopes=("levitate:contacts",)),
        "search_contacts": ScopeRequirement(scopes=("levitate:contacts",)),
        "list_contact_key_facts": ScopeRequirement(scopes=("levitate:contacts",)),
        "add_contact_key_fact": ScopeRequirement(scopes=("levitate:contacts",)),
        "get_contact_key_fact": ScopeRequirement(scopes=("levitate:contacts",)),
        "replace_contact_key_fact": ScopeRequirement(scopes=("levitate:contacts",)),
        "delete_contact_key_fact": ScopeRequirement(scopes=("levitate:contacts",)),
        "get_note": ScopeRequirement(scopes=("levitate:contacts",)),
        "delete_note": ScopeRequirement(scopes=("levitate:contacts",)),
        "list_notes": ScopeRequirement(scopes=("levitate:contacts",)),
        "create_note": ScopeRequirement(scopes=("levitate:contacts",)),
    },
)
