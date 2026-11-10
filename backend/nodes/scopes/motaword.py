"""Scopes in MotaWord OpenAPI 1.0 security requirements.

https://api.motaword.com/openapi.yaml
The public language/format catalogs are unauthenticated; other operations declare
mwoAuth/default. The token endpoint also documents privileged for private access:
https://docs.motaword.com/reference/getaccesstoken
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

MOTAWORD_SCOPES = ScopeRegistry(provider="motaword", requirements={
    name: ScopeRequirement(() if name in {"list_languages", "list_formats"} else ("default",))
    for name in (
        "get_account", "list_languages", "list_formats", "list_projects", "get_project",
        "create_project", "update_project", "launch_project", "cancel_project", "get_progress",
        "get_invoice", "list_documents", "get_document", "list_project_documents", "add_linked_document",
        "list_project_glossaries", "list_project_style_guides", "list_activities", "add_activity",
        "list_project_strings", "package_translations", "check_package", "on_project_status",
    )
})
