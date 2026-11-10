"""API-key scopes from the pinned Appwrite 2.3.0 x-appwrite.scope metadata.
https://appwrite.io/docs/advanced/platform/api-keys
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

APPWRITE_SCOPES = ScopeRegistry(provider="appwrite", requirements={
    'list_databases': ScopeRequirement(scopes=('databases.read',)),
    'list_tables': ScopeRequirement(scopes=('tables.read', 'collections.read')),
    'list_rows': ScopeRequirement(scopes=('rows.read', 'documents.read')),
    'get_row': ScopeRequirement(scopes=('rows.read', 'documents.read')),
    'create_row': ScopeRequirement(scopes=('rows.write', 'documents.write')),
    'update_row': ScopeRequirement(scopes=('rows.write', 'documents.write')),
    'upsert_row': ScopeRequirement(scopes=('rows.write', 'documents.write')),
    'delete_row': ScopeRequirement(scopes=('rows.write', 'documents.write')),
    'list_users': ScopeRequirement(scopes=('users.read',)),
    'get_user': ScopeRequirement(scopes=('users.read',)),
    'create_user': ScopeRequirement(scopes=('users.write',)),
    'update_user_preferences': ScopeRequirement(scopes=('users.write',)),
    'list_buckets': ScopeRequirement(scopes=('buckets.read',)),
    'get_bucket': ScopeRequirement(scopes=('buckets.read',)),
    'list_files': ScopeRequirement(scopes=('files.read',)),
    'get_file': ScopeRequirement(scopes=('files.read',)),
    'delete_file': ScopeRequirement(scopes=('files.write',)),
    'list_functions': ScopeRequirement(scopes=('functions.read',)),
    'create_execution': ScopeRequirement(scopes=('executions.write', 'execution.write')),
    'get_execution': ScopeRequirement(scopes=('executions.read', 'execution.read')),
    'list_teams': ScopeRequirement(scopes=('teams.read',)),
    'on_row_created': ScopeRequirement(scopes=('webhooks.write',)),
    'on_row_updated': ScopeRequirement(scopes=('webhooks.write',)),
    'on_user_created': ScopeRequirement(scopes=('webhooks.write',)),
    'on_file_uploaded': ScopeRequirement(scopes=('webhooks.write',)),
})
