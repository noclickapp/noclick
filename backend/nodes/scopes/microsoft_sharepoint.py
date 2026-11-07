"""SharePoint delegated Graph permissions: https://learn.microsoft.com/graph/api/."""

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

_SHAREPOINT_WRITE = ScopeRequirement(scopes=("https://graph.microsoft.com/Sites.ReadWrite.All",))

SHAREPOINT_SCOPES = ScopeRegistry(
    provider="sharepoint",
    requirements={
        "get_root_site": _SHAREPOINT_WRITE,
        "search_sites": _SHAREPOINT_WRITE,
        "get_site": _SHAREPOINT_WRITE,
        "list_lists": _SHAREPOINT_WRITE,
        "get_list": _SHAREPOINT_WRITE,
        "list_items": _SHAREPOINT_WRITE,
        "get_item": _SHAREPOINT_WRITE,
        "create_item": _SHAREPOINT_WRITE,
        "update_item": _SHAREPOINT_WRITE,
        "delete_item": _SHAREPOINT_WRITE,
        "list_libraries": _SHAREPOINT_WRITE,
        "list_files": _SHAREPOINT_WRITE,
        "get_file": _SHAREPOINT_WRITE,
        "upload_text_file": _SHAREPOINT_WRITE,
    },
)
