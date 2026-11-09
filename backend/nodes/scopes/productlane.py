"""Productlane v2 API-key scopes from the published 2.0.0 contract.

https://productlane.com/api/v2/openapi.json
https://productlane.com/docs/authentication
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

PRODUCTLANE_SCOPES = ScopeRegistry(provider="productlane", requirements={
    'get_me': ScopeRequirement(()),
    'list_threads': ScopeRequirement(('threads:read',)),
    'get_thread': ScopeRequirement(('threads:read',)),
    'create_thread': ScopeRequirement(('threads:write',)),
    'update_thread': ScopeRequirement(('threads:write',)),
    'list_messages': ScopeRequirement(('threads:read',)),
    'send_message': ScopeRequirement(('messages:write',)),
    'list_comments': ScopeRequirement(('threads:read',)),
    'create_comment': ScopeRequirement(('comments:write',)),
    'list_contacts': ScopeRequirement(('contacts:read',)),
    'get_contact': ScopeRequirement(('contacts:read',)),
    'create_contact': ScopeRequirement(('contacts:write',)),
    'update_contact': ScopeRequirement(('contacts:write',)),
    'list_companies': ScopeRequirement(('companies:read',)),
    'get_company': ScopeRequirement(('companies:read',)),
    'create_company': ScopeRequirement(('companies:write',)),
    'update_company': ScopeRequirement(('companies:write',)),
    'list_tags': ScopeRequirement(('tags:read',)),
    'list_projects': ScopeRequirement(('projects:read',)),
    'list_issues': ScopeRequirement(('issues:read',)),
    'list_changelogs': ScopeRequirement(('changelogs:read',)),
    'get_changelog': ScopeRequirement(('changelogs:read',)),
    'create_changelog': ScopeRequirement(('changelogs:write',)),
    'update_changelog': ScopeRequirement(('changelogs:write',)),
})
