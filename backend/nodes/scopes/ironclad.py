"""Ironclad token permissions from its published public API v1 contract.

https://developer.ironcladapp.com/openapi/ironclad-public-api.json
Pasted access tokens retain their existing grants; NoClick requests no consent.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

IRONCLAD_SCOPES = ScopeRegistry(
    provider="ironclad",
    requirements={
        'list_workflows': ScopeRequirement(('public.workflows.readWorkflows',)),
        'get_workflow': ScopeRequirement(('public.workflows.readWorkflows',)),
        'create_workflow': ScopeRequirement(('public.workflows.createWorkflows',)),
        'list_workflow_approvals': ScopeRequirement(('public.workflows.readApprovals',)),
        'list_workflow_signers': ScopeRequirement(('public.workflows.readSignatures',)),
        'list_workflow_participants': ScopeRequirement(('public.workflows.readParticipants',)),
        'list_workflow_comments': ScopeRequirement(('public.workflows.readComments',)),
        'create_workflow_comment': ScopeRequirement(('public.workflows.createComments',)),
        'update_workflow_attributes': ScopeRequirement(('public.workflows.updateWorkflows',)),
        'pause_workflow': ScopeRequirement(('public.workflows.pauseAndResume',)),
        'resume_workflow': ScopeRequirement(('public.workflows.pauseAndResume',)),
        'cancel_workflow': ScopeRequirement(('public.workflows.cancel',)),
        'list_workflow_schemas': ScopeRequirement(('public.workflows.readSchemas',)),
        'get_workflow_schema': ScopeRequirement(('public.workflows.readSchemas',)),
        'list_records': ScopeRequirement(('public.records.readRecords',)),
        'get_record': ScopeRequirement(('public.records.readRecords',)),
        'create_record': ScopeRequirement(('public.records.createRecords',)),
        'update_record': ScopeRequirement(('public.records.updateRecords',)),
        'delete_record': ScopeRequirement(('public.records.deleteRecords',)),
        'get_record_schema': ScopeRequirement(('public.records.readSchemas',)),
        'list_entities': ScopeRequirement(('public.entities.readEntities',)),
        'get_entity': ScopeRequirement(('public.entities.readEntities',)),
        'create_entity': ScopeRequirement(('public.entities.createEntities',)),
        'update_entity': ScopeRequirement(('public.entities.updateEntities',)),
    },
)
