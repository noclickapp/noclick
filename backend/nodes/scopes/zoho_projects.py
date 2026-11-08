"""Zoho Projects V3 scopes: https://projects.zoho.com/api-docs
Identity scope: https://www.zoho.com/developer/oauth/scope.html
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement

ZOHO_PROJECTS_SCOPES = ScopeRegistry(
    provider="zoho_projects",
    requirements={
        "list_portals": ScopeRequirement(scopes=("ZohoProjects.portals.READ",)),
        "get_portal": ScopeRequirement(scopes=("ZohoProjects.portals.READ",)),
        "list_projects": ScopeRequirement(scopes=("ZohoProjects.projects.READ",)),
        "get_project": ScopeRequirement(scopes=("ZohoProjects.projects.READ",)),
        "create_project": ScopeRequirement(scopes=("ZohoProjects.projects.CREATE",)),
        "update_project": ScopeRequirement(scopes=("ZohoProjects.projects.UPDATE",)),
        "trash_project": ScopeRequirement(scopes=("ZohoProjects.projects.UPDATE",)),
        "restore_project": ScopeRequirement(scopes=("ZohoProjects.projects.UPDATE",)),
        "delete_project": ScopeRequirement(scopes=("ZohoProjects.projects.DELETE",)),
        "list_tasklists": ScopeRequirement(scopes=("ZohoProjects.tasklists.READ",)),
        "list_all_tasklists": ScopeRequirement(scopes=("ZohoProjects.tasklists.READ",)),
        "get_tasklist": ScopeRequirement(scopes=("ZohoProjects.tasklists.READ",)),
        "create_tasklist": ScopeRequirement(scopes=("ZohoProjects.tasklists.CREATE",)),
        "update_tasklist": ScopeRequirement(scopes=("ZohoProjects.tasklists.CREATE",)),
        "delete_tasklist": ScopeRequirement(scopes=("ZohoProjects.tasklists.DELETE",)),
        "list_tasks": ScopeRequirement(scopes=("ZohoProjects.tasks.READ",)),
        "list_all_tasks": ScopeRequirement(scopes=("ZohoProjects.tasks.READ",)),
        "get_task": ScopeRequirement(scopes=("ZohoProjects.tasks.READ",)),
        "create_task": ScopeRequirement(scopes=("ZohoProjects.tasks.CREATE",)),
        "update_task": ScopeRequirement(scopes=("ZohoProjects.tasks.UPDATE",)),
        "delete_task": ScopeRequirement(scopes=("ZohoProjects.tasks.DELETE",)),
        "on_new_task": ScopeRequirement(scopes=("ZohoProjects.tasks.READ",)),
    },
    extra_scopes={"default": ("aaaserver.profile.READ",)},
    enforcement=Enforcement.STRICT,
)
