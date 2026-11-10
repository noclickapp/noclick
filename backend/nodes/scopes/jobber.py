"""App scopes configured in Developer Center, not negotiated per request.
https://developer.getjobber.com/docs/getting_started
https://developer.getjobber.com/docs/building_your_app/app_authorization
Account identity works regardless of configured scopes. Custom field configuration
reads and creation require their dedicated scopes (Connect/Grow/Plus plans).
Literal scope identifiers are published by the Developer Center:
https://developer.getjobber.com/component---src-pages-apps-index-tsx-e72a1a2ab48d80fb08ef.js
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
JOBBER_SCOPES = ScopeRegistry(provider="jobber", requirements={
    'get_account': ScopeRequirement(()),
    'list_clients': ScopeRequirement(('read_clients',)),
    'create_client': ScopeRequirement(('write_clients',)),
    'edit_client_custom_fields': ScopeRequirement(('write_clients',)),
    'list_jobs': ScopeRequirement(('read_clients', 'read_jobs')),
    'get_job': ScopeRequirement(('read_clients', 'read_jobs')),
    'list_quotes': ScopeRequirement(('read_clients', 'read_quotes')),
    'get_quote': ScopeRequirement(('read_clients', 'read_quotes')),
    'list_custom_field_configurations': ScopeRequirement(('read_custom_field_configurations',)),
    'create_link_configuration': ScopeRequirement(('read_custom_field_configurations', 'write_custom_field_configurations')),
})
