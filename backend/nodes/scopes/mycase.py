"""MyCase resource permissions are provisioned with the client by support.

No scope names or scope request parameter are published in Getting Started;
request no invented OAuth scopes. Resource access is checked by MyCase.
https://stoplight.io/api/v1/projects/mycaseapi/mycase-api-documentation/nodes/docs/Getting-Started.md
https://supportcenter.mycase.com/en/articles/9370198-open-api
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

MYCASE_SCOPES = ScopeRegistry(
    provider="mycase",
    requirements={name: ScopeRequirement(scopes=()) for name in (
        'on_new_or_updated_client',
        'on_new_or_updated_lead',
        'on_new_or_updated_case',
        'on_new_or_updated_task',
        'get_current_user',
        'list_clients',
        'get_client',
        'create_client',
        'update_client',
        'list_leads',
        'get_lead',
        'create_lead',
        'update_lead',
        'list_cases',
        'get_case',
        'create_case',
        'update_case',
        'list_tasks',
        'create_task',
        'update_task',
        'list_case_notes',
        'create_case_note',
        'get_note',
        'list_time_entries',
        'create_time_entry',
        'get_time_entry',
        'list_events',
        'create_event',
        'list_invoices',
    )},
)
