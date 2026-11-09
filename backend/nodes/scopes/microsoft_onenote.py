"""Delegated OneNote permissions: https://learn.microsoft.com/en-us/graph/permissions-reference#notesreadwrite"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

_NOTES_WRITE = ScopeRequirement(scopes=("https://graph.microsoft.com/Notes.ReadWrite",))
ONENOTE_SCOPES = ScopeRegistry(
    provider="microsoft-onenote",
    requirements={name: _NOTES_WRITE for name in (
        "list_notebooks", "get_notebook", "create_notebook",
        "list_notebook_sections", "list_sections", "get_section", "create_section",
        "list_section_groups", "get_section_group", "create_section_group",
        "list_pages", "list_section_pages", "get_page", "get_page_content",
        "get_page_preview", "create_page", "append_page_content",
        "replace_page_content", "delete_page", "on_new_page", "on_new_or_updated_page",
    )},
)
