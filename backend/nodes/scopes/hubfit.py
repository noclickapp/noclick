"""HubFit key permissions from each operation's published security requirement.

API keys are scoped in Settings > API, rather than through an OAuth consent flow.
Source: https://hubfit.com/developers/openapi.json
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

HUBFIT_SCOPES = ScopeRegistry(provider="hubfit", requirements={
    'list_clients': ScopeRequirement(('clients:read',)),
    'create_client': ScopeRequirement(('clients:create',)),
    'get_client': ScopeRequirement(('clients:read',)),
    'list_client_notes': ScopeRequirement(('clients:read',)),
    'create_client_note': ScopeRequirement(('clients:write',)),
    'send_client_message': ScopeRequirement(('messages:write',)),
    'list_tags': ScopeRequirement(('clients:read',)),
    'list_onboarding_flows': ScopeRequirement(('clients:create',)),
    'list_completed_workouts': ScopeRequirement(('clients:read',)),
    'get_completed_workout': ScopeRequirement(('clients:read',)),
    'list_check_in_submissions': ScopeRequirement(('clients:read',)),
    'get_check_in_submission': ScopeRequirement(('clients:read',)),
    'review_check_in_submission': ScopeRequirement(('check-ins:review',)),
    'get_questionnaire_submission': ScopeRequirement(('clients:read',)),
    'list_package_purchases': ScopeRequirement(('clients:read',)),
    'get_package_purchase': ScopeRequirement(('clients:read',)),
    'list_tasks': ScopeRequirement(('tasks:write',)),
    'create_task': ScopeRequirement(('tasks:write',)),
    'get_task': ScopeRequirement(('tasks:write',)),
    'update_task': ScopeRequirement(('tasks:write',)),
    'on_client_created': ScopeRequirement(('webhooks:write',)),
    'on_check_in_submitted': ScopeRequirement(('webhooks:write',)),
    'on_workout_completed': ScopeRequirement(('webhooks:write',)),
    'on_package_purchased': ScopeRequirement(('webhooks:write',)),
    'on_questionnaire_submitted': ScopeRequirement(('webhooks:write',)),
})
