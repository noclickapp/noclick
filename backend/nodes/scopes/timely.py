"""Timely V1 manage scope: https://developer.timely.com/."""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

TIMELY_SCOPES = ScopeRegistry(
    provider="timely",
    requirements={
        'list_clients': ScopeRequirement(scopes=("manage",)),
        'get_client': ScopeRequirement(scopes=("manage",)),
        'create_client': ScopeRequirement(scopes=("manage",)),
        'update_client': ScopeRequirement(scopes=("manage",)),
        'list_projects': ScopeRequirement(scopes=("manage",)),
        'get_project': ScopeRequirement(scopes=("manage",)),
        'create_project': ScopeRequirement(scopes=("manage",)),
        'update_project': ScopeRequirement(scopes=("manage",)),
        'delete_project': ScopeRequirement(scopes=("manage",)),
        'list_time_entries': ScopeRequirement(scopes=("manage",)),
        'get_time_entry': ScopeRequirement(scopes=("manage",)),
        'create_time_entry': ScopeRequirement(scopes=("manage",)),
        'update_time_entry': ScopeRequirement(scopes=("manage",)),
        'delete_time_entry': ScopeRequirement(scopes=("manage",)),
        'start_timer': ScopeRequirement(scopes=("manage",)),
        'stop_timer': ScopeRequirement(scopes=("manage",)),
        'get_current_user': ScopeRequirement(scopes=("manage",)),
        'list_users': ScopeRequirement(scopes=("manage",)),
    },
)
