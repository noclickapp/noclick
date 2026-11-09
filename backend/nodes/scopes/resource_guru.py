"""Resource Guru operation scopes from the provider's published OpenAPI contract.

https://resourceguruapp.com/docs/api#section/Authentication
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

RESOURCE_GURU_SCOPES = ScopeRegistry(provider="resource-guru", requirements={
    'get_me': ScopeRequirement(('users:read',)),
    'list_accounts': ScopeRequirement(('accounts:read',)),
    'list_bookings': ScopeRequirement(('bookings:read',)),
    'get_booking': ScopeRequirement(('bookings:read',)),
    'create_booking': ScopeRequirement(('bookings:write',)),
    'update_booking': ScopeRequirement(('bookings:write',)),
    'delete_booking': ScopeRequirement(('bookings:write',)),
    'list_clients': ScopeRequirement(('clients:read',)),
    'get_client': ScopeRequirement(('clients:read',)),
    'create_client': ScopeRequirement(('clients:write',)),
    'update_client': ScopeRequirement(('clients:write',)),
    'delete_client': ScopeRequirement(('clients:write',)),
    'list_projects': ScopeRequirement(('projects:read',)),
    'get_project': ScopeRequirement(('projects:read',)),
    'create_project': ScopeRequirement(('projects:write',)),
    'update_project': ScopeRequirement(('projects:write',)),
    'delete_project': ScopeRequirement(('projects:write',)),
    'list_resources': ScopeRequirement(('resources:read',)),
    'get_resource': ScopeRequirement(('resources:read',)),
    'create_resource': ScopeRequirement(('resources:write',)),
    'update_resource': ScopeRequirement(('resources:write',)),
    'list_downtimes': ScopeRequirement(('downtimes:read',)),
    'create_downtime': ScopeRequirement(('downtimes:write',)),
    'delete_downtime': ScopeRequirement(('downtimes:write',)),
    'on_client_changed': ScopeRequirement(('webhooks:write',)),
})
