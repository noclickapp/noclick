"""awork v1 uses full_access for every OAuth operation in the published contract.

The manual API key has permanent workspace admin access, equivalent to this
API permission set; no OAuth consent is performed for API keys.
Source: https://developers.awork.com/authentication
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

AWORK_SCOPES = ScopeRegistry(provider="awork", requirements={
    "list_projects": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "get_project": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "create_project": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "update_project": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "list_tasks": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "list_project_tasks": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "get_task": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "create_task": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "update_task": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "list_task_comments": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "create_task_comment": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "list_project_comments": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "create_project_comment": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "list_companies": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "get_company": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "create_company": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "update_company": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "list_users": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "list_time_entries": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "get_time_entry": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "create_time_entry": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "list_types_of_work": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
    "on_project_created": ScopeRequirement(("full_access",), credential_types=("awork_api_key",)),
})
