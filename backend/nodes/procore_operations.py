"""One published Procore REST operation per workflow operation.

Contract: https://developers.procore.com/api/v1/resource_groups/full_oas
Tuples contain HTTP method, path template and request-body wrapper.
"""
PROCORE_OPERATIONS = {
    'get_current_user': ('GET', '/rest/v1.0/me', None),
    'list_companies': ('GET', '/rest/v1.0/companies', None),
    'list_projects': ('GET', '/rest/v1.0/projects', None),
    'get_project': ('GET', '/rest/v1.0/projects/{project_id}', None),
    'create_project': ('POST', '/rest/v1.0/projects', 'project'),
    'update_project': ('PATCH', '/rest/v1.0/projects/{project_id}', 'project'),
    'list_vendors': ('GET', '/rest/v1.0/vendors', None),
    'get_vendor': ('GET', '/rest/v1.0/vendors/{vendor_id}', None),
    'create_vendor': ('POST', '/rest/v1.0/vendors', 'vendor'),
    'update_vendor': ('PATCH', '/rest/v1.0/vendors/{vendor_id}', 'vendor'),
    'list_project_users': ('GET', '/rest/v1.0/projects/{project_id}/users', None),
    'list_rfis': ('GET', '/rest/v1.0/projects/{project_id}/rfis', None),
    'get_rfi': ('GET', '/rest/v1.0/projects/{project_id}/rfis/{rfi_id}', None),
    'create_rfi': ('POST', '/rest/v1.0/projects/{project_id}/rfis', 'rfi'),
    'update_rfi': ('PATCH', '/rest/v1.0/projects/{project_id}/rfis/{rfi_id}', 'rfi'),
    'list_submittals': ('GET', '/rest/v1.1/projects/{project_id}/submittals', None),
    'get_submittal': ('GET', '/rest/v1.1/projects/{project_id}/submittals/{submittal_id}', None),
    'create_submittal': ('POST', '/rest/v1.1/projects/{project_id}/submittals', 'submittal'),
    'list_notes_logs': ('GET', '/rest/v1.0/projects/{project_id}/notes_logs', None),
    'create_notes_log': ('POST', '/rest/v1.0/projects/{project_id}/notes_logs', 'notes_log'),
    'list_locations': ('GET', '/rest/v1.0/projects/{project_id}/locations', None),
    'create_location': ('POST', '/rest/v1.0/projects/{project_id}/locations', 'location'),
}
