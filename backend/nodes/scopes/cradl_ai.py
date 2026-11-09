"""Scope requirements from Cradl AI's published 2026-07-02 v1 contract.

These operation keys document permissions for pasted bearer tokens as well as
connection evidence. NoClick does not initiate an OAuth sign-in for this node.
Source: https://docs.cradl.ai/api-reference/openapi.json
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

CRADL_AI_SCOPES = ScopeRegistry('cradl_ai', {
    'list_agents': ScopeRequirement(scopes=('agents:read',)),
    'get_agent': ScopeRequirement(scopes=('agents:read',)),
    'list_agent_runs': ScopeRequirement(scopes=('agents.runs:read',)),
    'create_agent_run': ScopeRequirement(scopes=('agents.runs:write',)),
    'get_agent_run': ScopeRequirement(scopes=('agents.runs:read',)),
    'archive_agent_run': ScopeRequirement(scopes=('agents.runs:write',)),
    # The provider contract explicitly specifies read for these two DELETEs.
    'delete_agent_run': ScopeRequirement(scopes=('agents.runs:read',)),
    'get_agent_statistics': ScopeRequirement(scopes=('agents.statistics:read',)),
    'list_documents': ScopeRequirement(scopes=('documents:read',)),
    'create_document': ScopeRequirement(scopes=('documents:write',)),
    'get_document': ScopeRequirement(scopes=('documents:read',)),
    'update_document': ScopeRequirement(scopes=('documents:write',)),
    'delete_document': ScopeRequirement(scopes=('documents:read',)),
    'list_predictions': ScopeRequirement(scopes=('predictions:read',)),
    'create_prediction': ScopeRequirement(scopes=('predictions:write',)),
    'get_prediction': ScopeRequirement(scopes=('predictions:read',)),
    'list_models': ScopeRequirement(scopes=('models:read',)),
    'get_model': ScopeRequirement(scopes=('models:read',)),
    'list_validations': ScopeRequirement(scopes=('validations:read',)),
    'get_validation': ScopeRequirement(scopes=('validations:read',)),
    'list_validation_tasks': ScopeRequirement(scopes=('validations.tasks:read',)),
    'create_validation_task': ScopeRequirement(scopes=('validations.tasks:write',)),
    'get_validation_task': ScopeRequirement(scopes=('validations.tasks:read',)),
    'update_validation_task': ScopeRequirement(scopes=('validations.tasks:write',)),
})
