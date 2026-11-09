"""Scopes from Zoho Writer's published OpenAPI 1.0.0 operation security declarations.
https://www.zoho.com/sites/zweb/images/writer/zoho-writer-oas-specs.zip
Identity: https://www.zoho.com/workdrive/developer/docs/api/v1/get-user-info.html
"""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
ZOHO_WRITER_SCOPES = ScopeRegistry(provider="zoho_writer", enforcement=Enforcement.STRICT,
    extra_scopes={"default": ("WorkDrive.users.READ",)}, requirements={
    'create_document': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
    'list_documents': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
    'search_documents': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL', 'ZohoSearch.securesearch.READ', 'WorkDrive.team.READ')),
    'get_document': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
    'get_document_metrics': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
    'get_document_fields': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
    'update_document_metadata': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
    'copy_document': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
    'trash_document': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
    'restore_document': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
    'list_templates': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
    'create_template': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
    'get_template': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
    'copy_template': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
    'delete_template': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
    'publish_document': ScopeRequirement(('ZohoWriter.documentEditor.ALL',)),
    'unpublish_document': ScopeRequirement(('ZohoWriter.documentEditor.ALL',)),
    'on_new_or_updated_document': ScopeRequirement(('ZohoWriter.documentEditor.ALL', 'WorkDrive.files.ALL', 'WorkDrive.organization.ALL', 'WorkDrive.workspace.ALL')),
})
