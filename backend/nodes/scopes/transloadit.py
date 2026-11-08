"""API2 token requirements from https://api2.transloadit.com/openapi.json, 2.0.0.

Tokens are pasted, not authorized through an interactive OAuth flow.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

TRANSLOADIT_SCOPES = ScopeRegistry("transloadit", {
    "list_assemblies": ScopeRequirement(("assemblies:read",)),
    "create_assembly": ScopeRequirement(("assemblies:write",)),
    "get_assembly": ScopeRequirement(),
    "cancel_assembly": ScopeRequirement(),
    "replay_assembly": ScopeRequirement(("assemblies:write",)),
    "list_assembly_notifications": ScopeRequirement(),
    "replay_assembly_notification": ScopeRequirement(("assemblies:write",)),
    "list_templates": ScopeRequirement(("templates:read",)),
    "get_template": ScopeRequirement(("templates:read",)),
    "create_template": ScopeRequirement(("templates:write",)),
    "update_template": ScopeRequirement(("templates:write",)),
    "delete_template": ScopeRequirement(("templates:write",)),
    "list_template_credentials": ScopeRequirement(("template_credentials:read",)),
    "list_template_credential_types": ScopeRequirement(),
    "get_template_credential": ScopeRequirement(("template_credentials:read",)),
    "delete_template_credential": ScopeRequirement(("template_credentials:write",)),
})
