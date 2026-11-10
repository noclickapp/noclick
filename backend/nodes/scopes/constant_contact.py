"""Scopes: https://developer.constantcontact.com/api_guide/scopes.html"""
from nodes.constant_contact_operations import OPERATIONS
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

CONSTANT_CONTACT_SCOPES = ScopeRegistry(
    provider="constant_contact",
    requirements={**{name: ScopeRequirement(scopes=op.scopes) for name, op in OPERATIONS.items()},
                  "on_new_contact": ScopeRequirement(scopes=("contact_data",))},
    extra_scopes={"default": ("offline_access",)},
)
