"""Least-privilege operation scopes from Houzz Pro API v0.2.0.

https://developer.houzz.com/docs/guides/scopes
For notes the provider accepts either project or lead scopes; project-owned
operations here choose the project scope. Provider enforcement is authoritative
for manually supplied tokens; no OAuth popup is advertised.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

HOUZZ_PRO_SCOPES = ScopeRegistry(provider="houzz-pro", requirements={
    # Webhook subscriptions need a valid token, but no named scope (provider docs).
    'on_project_updated': ScopeRequirement(scopes=()),
    'list_projects': ScopeRequirement(scopes=('read:projects',)),
    'get_project': ScopeRequirement(scopes=('read:projects',)),
    'create_project': ScopeRequirement(scopes=('write:projects',)),
    'update_project': ScopeRequirement(scopes=('write:projects',)),
    'list_leads': ScopeRequirement(scopes=('read:leads',)),
    'get_lead': ScopeRequirement(scopes=('read:leads',)),
    'create_lead': ScopeRequirement(scopes=('write:leads',)),
    'update_lead': ScopeRequirement(scopes=('write:leads',)),
    'list_contacts': ScopeRequirement(scopes=('read:contacts',)),
    'get_contact': ScopeRequirement(scopes=('read:contacts',)),
    'create_contact': ScopeRequirement(scopes=('write:contacts',)),
    'update_contact': ScopeRequirement(scopes=('write:contacts',)),
    'convert_lead': ScopeRequirement(scopes=('write:projects', 'write:leads')),
    'retire_lead': ScopeRequirement(scopes=('write:leads',)),
    'reactivate_lead': ScopeRequirement(scopes=('write:leads',)),
    'update_lead_phase': ScopeRequirement(scopes=('write:leads',)),
    'list_project_tasks': ScopeRequirement(scopes=('read:tasks',)),
    'create_project_task': ScopeRequirement(scopes=('write:tasks',)),
    'get_task': ScopeRequirement(scopes=('read:tasks',)),
    'update_task': ScopeRequirement(scopes=('write:tasks',)),
    'list_project_notes': ScopeRequirement(scopes=('read:projects',)),
    'create_project_note': ScopeRequirement(scopes=('write:projects',)),
    'list_project_statuses': ScopeRequirement(scopes=('read:projects',)),
    'list_lead_phases': ScopeRequirement(scopes=('read:leads',)),
})
