"""FieldView OAuth permissions for the v4 operations this node exposes.

Source: https://dev.fieldview.com/openapi/platform.yaml (4.0.11), including
content-dependent export scopes in the endpoint description.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

CLIMATE_SCOPES = ScopeRegistry(provider="climate", requirements={
    'list_fields': ScopeRequirement(scopes=('fields:read',)),
    'get_field': ScopeRequirement(scopes=('fields:read',)),
    'list_operations': ScopeRequirement(scopes=('operations:read',)),
    'get_resource_owner': ScopeRequirement(scopes=('resourceOwners:read',)),
    'get_boundary': ScopeRequirement(scopes=('fields:read',)),
    'query_boundaries': ScopeRequirement(scopes=('fields:read',)),
    'upload_boundary': ScopeRequirement(scopes=('boundaries:write',)),
    'create_upload': ScopeRequirement(scopes=('fields:write',)),
    'upload_chunk': ScopeRequirement(scopes=('fields:write',)),
    'get_upload_status': ScopeRequirement(scopes=('fields:write',)),
    'query_upload_statuses': ScopeRequirement(scopes=('fields:write',)),
    'create_export': ScopeRequirement(scopes=('exports:read', 'plantingActivitySummary:read')),
    'download_export_chunk': ScopeRequirement(scopes=('exports:read',)),
    'get_export_status': ScopeRequirement(scopes=('exports:read',)),
    'list_scouting_observations': ScopeRequirement(scopes=('scouting:read',)),
    'get_scouting_observation': ScopeRequirement(scopes=('scouting:read',)),
    'list_planting_activities': ScopeRequirement(scopes=('asPlanted:read',)),
    'get_planting_summary': ScopeRequirement(scopes=('asPlanted:read',)),
    'on_updated_planting_activity': ScopeRequirement(scopes=('asPlanted:read',)),
    'list_application_activities': ScopeRequirement(scopes=('asApplied:read',)),
    'get_application_summary': ScopeRequirement(scopes=('asApplied:read',)),
    'on_updated_application_activity': ScopeRequirement(scopes=('asApplied:read',)),
    'list_harvest_activities': ScopeRequirement(scopes=('asHarvested:read',)),
    'get_harvest_summary': ScopeRequirement(scopes=('asHarvested:read',)),
    'on_updated_harvest_activity': ScopeRequirement(scopes=('asHarvested:read',)),
})
