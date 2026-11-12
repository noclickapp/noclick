"""Neon API v2 workflow node.

The endpoint catalog below is generated from Neon's official OpenAPI document
in neondatabase/neon-pkgs. Path parameters are explicit node fields; optional
query parameters and JSON request bodies use JSON editors so the API stays
usable as Neon adds fields without a handwritten model for every endpoint.
"""

from __future__ import annotations

import json
import re
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence


API_BASE = "https://console.neon.tech/api/v2"


class NeonApiKeyCredential(BaseModel):
    credential_type: Literal["neon_api_key"] = Field(
        "neon_api_key", json_schema_extra={"ui:hidden": True},
    )
    model_config = ConfigDict(title="Neon API Key", json_schema_extra={
        "x-credential-url": "https://console.neon.tech/app/settings#api-keys",
    })
    api_key: str = Field(..., title="Neon API key", json_schema_extra={"ui:widget": "password"},
                         description="Personal, organization, or project-scoped API key")


# Neon's own MCP server: agents get its tools through a person's Neon sign-in.
NeonMcpCredential = mcp_credential("neon", "https://mcp.neon.tech/mcp", app="Neon")
NeonCredential = Union[NeonApiKeyCredential, NeonMcpCredential]


# action -> (method, path, category, label, body_requirement, required_query, query_names)
# body_requirement is None for no body, False for optional, True for required.
# Source: https://github.com/neondatabase/neon-pkgs/blob/main/packages/sdk/spec/neon-openapi.json
NEON_ENDPOINTS: Dict[str, tuple[str, str, str, str, Optional[bool], tuple[str, ...], tuple[str, ...]]] = {
    'accept_project_transfer_request': ('PUT', '/projects/{project_id}/transfer_requests/{request_id}', 'Project', 'Accept a project transfer request', False, (), ()),
    'add_branch_neon_auth_oauth_provider': ('POST', '/projects/{project_id}/branches/{branch_id}/auth/oauth_providers', 'Auth', 'Add an OAuth provider', True, (), ()),
    'add_branch_neon_auth_trusted_domain': ('POST', '/projects/{project_id}/branches/{branch_id}/auth/domains', 'Auth', 'Add domain to redirect_uri whitelist', True, (), ()),
    'add_neon_auth_domain_to_redirect_uri_whitelist': ('POST', '/projects/{project_id}/auth/domains', 'Auth (legacy)', 'Add trusted redirect URI domain', True, (), ()),
    'add_neon_auth_oauth_provider': ('POST', '/projects/{project_id}/auth/oauth_providers', 'Auth (legacy)', 'Add an OAuth provider', True, (), ()),
    'add_project_jwks': ('POST', '/projects/{project_id}/jwks', 'Project', 'Add JWKS URL', True, (), ()),
    'assign_organization_vpc_endpoint': ('POST', '/organizations/{org_id}/vpc/region/{region_id}/vpc_endpoints/{vpc_endpoint_id}', 'Organizations', 'Assign or update VPC endpoint', True, (), ()),
    'assign_project_vpc_endpoint': ('POST', '/projects/{project_id}/vpc_endpoints/{vpc_endpoint_id}', 'Project', 'Set VPC endpoint restriction', True, (), ()),
    'count_project_branches': ('GET', '/projects/{project_id}/branches/count', 'Branch', 'Retrieve number of branches', None, (), ('search',)),
    'create_api_key': ('POST', '/api_keys', 'API Key', 'Create API key', True, (), ()),
    'create_branch_neon_auth_new_user': ('POST', '/projects/{project_id}/branches/{branch_id}/auth/users', 'Auth', 'Create new auth user', True, (), ()),
    'create_credential': ('POST', '/projects/{project_id}/branches/{branch_id}/credentials', 'Credentials', 'Issue a scoped credential on the branch', True, (), ()),
    'create_neon_auth': ('POST', '/projects/{project_id}/branches/{branch_id}/auth', 'Auth', 'Enable Neon Auth for the branch', True, (), ()),
    'create_neon_auth_integration': ('POST', '/projects/auth/create', 'Auth (legacy)', 'Create Neon Auth integration', True, (), ()),
    'create_neon_auth_new_user': ('POST', '/projects/auth/user', 'Auth (legacy)', 'Create new auth user', True, (), ()),
    'create_neon_auth_provider_sdk_keys': ('POST', '/projects/auth/keys', 'Auth (legacy)', 'Create Auth Provider SDK keys', True, (), ()),
    'create_org_api_key': ('POST', '/organizations/{org_id}/api_keys', 'Organizations', 'Create organization API key', True, (), ()),
    'create_organization_invitations': ('POST', '/organizations/{org_id}/invitations', 'Organizations', 'Create organization invitations', True, (), ()),
    'create_project': ('POST', '/projects', 'Project', 'Create project', True, (), ()),
    'create_project_branch': ('POST', '/projects/{project_id}/branches', 'Branch', 'Create branch', False, (), ()),
    'create_project_branch_anonymized': ('POST', '/projects/{project_id}/branch_anonymized', 'Branch', 'Create anonymized branch', True, (), ()),
    'create_project_branch_bucket': ('POST', '/projects/{project_id}/branches/{branch_id}/buckets', 'Buckets', 'Create a bucket on the branch', True, (), ()),
    'create_project_branch_data_api': ('POST', '/projects/{project_id}/branches/{branch_id}/data-api/{database_name}', 'DataAPI', 'Create Neon Data API', False, (), ()),
    'create_project_branch_database': ('POST', '/projects/{project_id}/branches/{branch_id}/databases', 'Branch', 'Create database', True, (), ()),
    'create_project_branch_role': ('POST', '/projects/{project_id}/branches/{branch_id}/roles', 'Branch', 'Create role', True, (), ()),
    'create_project_branch_trigger': ('POST', '/projects/{project_id}/branches/{branch_id}/triggers', 'Functions', 'Create a trigger', True, (), ()),
    'create_project_endpoint': ('POST', '/projects/{project_id}/endpoints', 'Endpoint', 'Create compute endpoint', True, (), ()),
    'create_project_transfer_request': ('POST', '/projects/{project_id}/transfer_requests', 'Project', 'Create a project transfer request', False, (), ()),
    'create_snapshot': ('POST', '/projects/{project_id}/branches/{branch_id}/snapshot', 'Snapshot', 'Create snapshot', None, (), ('expires_at', 'lsn', 'name', 'slug', 'timestamp')),
    'delete_branch_neon_auth_oauth_provider': ('DELETE', '/projects/{project_id}/branches/{branch_id}/auth/oauth_providers/{oauth_provider_id}', 'Auth', 'Delete OAuth provider', None, (), ()),
    'delete_branch_neon_auth_trusted_domain': ('DELETE', '/projects/{project_id}/branches/{branch_id}/auth/domains', 'Auth', 'Delete domain from redirect_uri whitelist', True, (), ()),
    'delete_branch_neon_auth_user': ('DELETE', '/projects/{project_id}/branches/{branch_id}/auth/users/{auth_user_id}', 'Auth', 'Delete auth user', None, (), ()),
    'delete_neon_auth_domain_from_redirect_uri_whitelist': ('DELETE', '/projects/{project_id}/auth/domains', 'Auth (legacy)', 'Delete trusted redirect URI domain', True, (), ()),
    'delete_neon_auth_integration': ('DELETE', '/projects/{project_id}/auth/integration/{auth_provider}', 'Auth (legacy)', 'Delete integration with auth provider', False, (), ()),
    'delete_neon_auth_oauth_provider': ('DELETE', '/projects/{project_id}/auth/oauth_providers/{oauth_provider_id}', 'Auth (legacy)', 'Delete OAuth provider', None, (), ()),
    'delete_neon_auth_user': ('DELETE', '/projects/{project_id}/auth/users/{auth_user_id}', 'Auth (legacy)', 'Delete auth user', None, (), ()),
    'delete_organization_spending_limit': ('DELETE', '/organizations/{org_id}/billing/spending_limit', 'Organizations', 'Remove organization spending limit', None, (), ()),
    'delete_organization_vpc_endpoint': ('DELETE', '/organizations/{org_id}/vpc/region/{region_id}/vpc_endpoints/{vpc_endpoint_id}', 'Organizations', 'Delete VPC endpoint', None, (), ()),
    'delete_project': ('DELETE', '/projects/{project_id}', 'Project', 'Delete project', None, (), ()),
    'delete_project_branch': ('DELETE', '/projects/{project_id}/branches/{branch_id}', 'Branch', 'Delete branch', None, (), ()),
    'delete_project_branch_bucket': ('DELETE', '/projects/{project_id}/branches/{branch_id}/buckets/{bucket_name}', 'Buckets', 'Delete a bucket on the branch', None, (), ()),
    'delete_project_branch_bucket_object': ('DELETE', '/projects/{project_id}/branches/{branch_id}/buckets/{bucket_name}/objects/{object_key}', 'Buckets', 'Delete an object in a bucket', None, (), ()),
    'delete_project_branch_bucket_objects_by_prefix': ('DELETE', '/projects/{project_id}/branches/{branch_id}/buckets/{bucket_name}/objects-by-prefix', 'Buckets', 'Delete every object under a key prefix (folder) in a bucket', None, ('prefix',), ('prefix',)),
    'delete_project_branch_custom_domain': ('DELETE', '/projects/{project_id}/branches/{branch_id}/custom-domains/{domain}', 'Functions', 'Delete a custom domain from a branch', None, (), ()),
    'delete_project_branch_data_api': ('DELETE', '/projects/{project_id}/branches/{branch_id}/data-api/{database_name}', 'DataAPI', 'Delete Neon Data API', None, (), ()),
    'delete_project_branch_database': ('DELETE', '/projects/{project_id}/branches/{branch_id}/databases/{database_name}', 'Branch', 'Delete database', None, (), ()),
    'delete_project_branch_function': ('DELETE', '/projects/{project_id}/branches/{branch_id}/functions/{slug}', 'Functions', 'Delete a function on the branch', None, (), ()),
    'delete_project_branch_role': ('DELETE', '/projects/{project_id}/branches/{branch_id}/roles/{role_name}', 'Branch', 'Delete role', None, (), ()),
    'delete_project_branch_trigger': ('DELETE', '/projects/{project_id}/branches/{branch_id}/triggers/{trigger_id}', 'Functions', 'Delete a trigger', None, (), ()),
    'delete_project_endpoint': ('DELETE', '/projects/{project_id}/endpoints/{endpoint_id}', 'Endpoint', 'Delete compute endpoint', None, (), ()),
    'delete_project_jwks': ('DELETE', '/projects/{project_id}/jwks/{jwks_id}', 'Project', 'Delete JWKS URL', None, (), ()),
    'delete_project_vpc_endpoint': ('DELETE', '/projects/{project_id}/vpc_endpoints/{vpc_endpoint_id}', 'Project', 'Delete VPC endpoint restriction', None, (), ()),
    'delete_snapshot': ('DELETE', '/projects/{project_id}/snapshots/{snapshot_id}', 'Snapshot', 'Delete snapshot', None, (), ()),
    'disable_neon_auth': ('DELETE', '/projects/{project_id}/branches/{branch_id}/auth', 'Auth', 'Disable Neon Auth for the branch', False, (), ()),
    'finalize_restore_branch': ('POST', '/projects/{project_id}/branches/{branch_id}/finalize_restore', 'Branch', 'Finalize branch restore from snapshot', False, (), ()),
    'get_active_regions': ('GET', '/regions', 'Region', 'List supported regions', None, (), ('org_id',)),
    'get_anonymized_branch_status': ('GET', '/projects/{project_id}/branches/{branch_id}/anonymized_status', 'Branch', 'Retrieve anonymized branch status', None, (), ()),
    'get_auth_details': ('GET', '/auth', 'Users', 'Retrieve request authentication details', None, (), ()),
    'get_available_preload_libraries': ('GET', '/projects/{project_id}/available_preload_libraries', 'Project', 'List available shared preload libraries', None, (), ()),
    'get_connection_uri': ('GET', '/projects/{project_id}/connection_uri', 'Project', 'Retrieve connection URI', None, ('database_name', 'role_name'), ('branch_id', 'database_name', 'endpoint_id', 'pooled', 'role_name')),
    'get_consumption_history_per_branch_v2': ('GET', '/consumption_history/v2/branches', 'Consumption', 'Retrieve branch consumption metrics', None, ('from', 'granularity', 'metrics', 'org_id', 'project_ids', 'to'), ('branch_ids', 'cursor', 'from', 'granularity', 'limit', 'metrics', 'org_id', 'project_ids', 'to')),
    'get_consumption_history_per_project': ('GET', '/consumption_history/projects', 'Consumption', 'Retrieve project consumption metrics (legacy plans)', None, ('from', 'granularity', 'to'), ('cursor', 'from', 'granularity', 'include_v1_metrics', 'limit', 'metrics', 'org_id', 'project_ids', 'to')),
    'get_consumption_history_per_project_v2': ('GET', '/consumption_history/v2/projects', 'Consumption', 'Retrieve project consumption metrics', None, ('from', 'granularity', 'metrics', 'org_id', 'to'), ('cursor', 'from', 'granularity', 'limit', 'metrics', 'org_id', 'project_ids', 'to')),
    'get_current_user_info': ('GET', '/users/me', 'Users', 'Retrieve current user details', None, (), ()),
    'get_current_user_organizations': ('GET', '/users/me/organizations', 'Users', 'List organizations for the current user', None, (), ()),
    'get_masking_rules': ('GET', '/projects/{project_id}/branches/{branch_id}/masking_rules', 'Branch', 'Retrieve masking rules', None, (), ()),
    'get_neon_auth': ('GET', '/projects/{project_id}/branches/{branch_id}/auth', 'Auth', 'Retrieve Neon Auth details for the branch', None, (), ()),
    'get_neon_auth_allow_localhost': ('GET', '/projects/{project_id}/branches/{branch_id}/auth/allow_localhost', 'Auth', 'Retrieve localhost allow setting', None, (), ()),
    'get_neon_auth_email_and_password_config': ('GET', '/projects/{project_id}/branches/{branch_id}/auth/email_and_password', 'Auth', 'Retrieve email and password configuration', None, (), ()),
    'get_neon_auth_email_provider': ('GET', '/projects/{project_id}/branches/{branch_id}/auth/email_provider', 'Auth', 'Retrieve email provider configuration', None, (), ()),
    'get_neon_auth_email_server': ('GET', '/projects/{project_id}/auth/email_server', 'Auth (legacy)', 'Retrieve email server configuration', None, (), ()),
    'get_neon_auth_phone_number_plugin': ('GET', '/projects/{project_id}/branches/{branch_id}/auth/plugins/phone-number', 'Auth', 'Retrieve phone number plugin configuration', None, (), ()),
    'get_neon_auth_plugin_configs': ('GET', '/projects/{project_id}/branches/{branch_id}/auth/plugins', 'Auth', 'Retrieve Neon Auth plugin configurations', None, (), ()),
    'get_neon_auth_webhook_config': ('GET', '/projects/{project_id}/branches/{branch_id}/auth/webhooks', 'Auth', 'Retrieve Neon Auth webhook configuration', None, (), ()),
    'get_organization': ('GET', '/organizations/{org_id}', 'Organizations', 'Retrieve organization details', None, (), ()),
    'get_organization_invitations': ('GET', '/organizations/{org_id}/invitations', 'Organizations', 'List organization invitations', None, (), ()),
    'get_organization_member': ('GET', '/organizations/{org_id}/members/{member_id}', 'Organizations', 'Retrieve organization member details', None, (), ()),
    'get_organization_members': ('GET', '/organizations/{org_id}/members', 'Organizations', 'List organization members', None, (), ('cursor', 'limit', 'sort_by', 'sort_order')),
    'get_organization_spending_limit': ('GET', '/organizations/{org_id}/billing/spending_limit', 'Organizations', 'Retrieve organization spending limit', None, (), ()),
    'get_organization_vpc_endpoint_details': ('GET', '/organizations/{org_id}/vpc/region/{region_id}/vpc_endpoints/{vpc_endpoint_id}', 'Organizations', 'Retrieve VPC endpoint details', None, (), ()),
    'get_project': ('GET', '/projects/{project_id}', 'Project', 'Retrieve project details', None, (), ()),
    'get_project_advisor_security_issues': ('GET', '/projects/{project_id}/advisors', 'Project', 'Get advisor issues', None, (), ('branch_id', 'category', 'database_name', 'min_severity')),
    'get_project_branch': ('GET', '/projects/{project_id}/branches/{branch_id}', 'Branch', 'Retrieve branch details', None, (), ()),
    'get_project_branch_ai_gateway': ('GET', '/projects/{project_id}/branches/{branch_id}/ai_gateway', 'AI Gateway', 'Get branch AI Gateway endpoint', None, (), ()),
    'get_project_branch_data_api': ('GET', '/projects/{project_id}/branches/{branch_id}/data-api/{database_name}', 'DataAPI', 'Retrieve Neon Data API configuration', None, (), ()),
    'get_project_branch_database': ('GET', '/projects/{project_id}/branches/{branch_id}/databases/{database_name}', 'Branch', 'Retrieve database details', None, (), ()),
    'get_project_branch_function': ('GET', '/projects/{project_id}/branches/{branch_id}/functions/{slug}', 'Functions', 'Get function details', None, (), ()),
    'get_project_branch_role': ('GET', '/projects/{project_id}/branches/{branch_id}/roles/{role_name}', 'Branch', 'Retrieve role details', None, (), ()),
    'get_project_branch_role_password': ('GET', '/projects/{project_id}/branches/{branch_id}/roles/{role_name}/reveal_password', 'Branch', 'Retrieve role password', None, (), ()),
    'get_project_branch_schema': ('GET', '/projects/{project_id}/branches/{branch_id}/schema', 'Branch', 'Retrieve database schema', None, ('db_name',), ('db_name', 'format', 'lsn', 'timestamp')),
    'get_project_branch_schema_comparison': ('GET', '/projects/{project_id}/branches/{branch_id}/compare_schema', 'Branch', 'Compare database schema', None, ('db_name',), ('base_branch_id', 'base_lsn', 'base_timestamp', 'db_name', 'lsn', 'timestamp')),
    'get_project_branch_storage': ('GET', '/projects/{project_id}/branches/{branch_id}/storage', 'Storage', 'Get branch object storage state', None, (), ()),
    'get_project_branch_trigger': ('GET', '/projects/{project_id}/branches/{branch_id}/triggers/{trigger_id}', 'Functions', 'Get a trigger', None, (), ()),
    'get_project_endpoint': ('GET', '/projects/{project_id}/endpoints/{endpoint_id}', 'Endpoint', 'Retrieve compute endpoint details', None, (), ()),
    'get_project_jwks': ('GET', '/projects/{project_id}/jwks', 'Project', 'List JWKS URLs', None, (), ()),
    'get_project_operation': ('GET', '/projects/{project_id}/operations/{operation_id}', 'Operation', 'Retrieve operation details', None, (), ()),
    'get_snapshot_schedule': ('GET', '/projects/{project_id}/branches/{branch_id}/backup_schedule', 'Snapshot', 'Retrieve backup schedule', None, (), ()),
    'grant_permission_to_project': ('POST', '/projects/{project_id}/permissions', 'Project', 'Grant project access', True, (), ()),
    'list_api_keys': ('GET', '/api_keys', 'API Key', 'List API keys', None, (), ()),
    'list_branch_neon_auth_oauth_providers': ('GET', '/projects/{project_id}/branches/{branch_id}/auth/oauth_providers', 'Auth', 'List OAuth providers for the branch', None, (), ()),
    'list_branch_neon_auth_trusted_domains': ('GET', '/projects/{project_id}/branches/{branch_id}/auth/domains', 'Auth', 'List domains in redirect_uri whitelist', None, (), ()),
    'list_credentials': ('GET', '/projects/{project_id}/branches/{branch_id}/credentials', 'Credentials', 'List credentials on the branch', None, (), ()),
    'list_neon_auth_integrations': ('GET', '/projects/{project_id}/auth/integrations', 'Auth (legacy)', 'List active integrations with auth providers', None, (), ()),
    'list_neon_auth_oauth_providers': ('GET', '/projects/{project_id}/auth/oauth_providers', 'Auth (legacy)', 'List OAuth providers', None, (), ()),
    'list_neon_auth_redirect_uri_whitelist_domains': ('GET', '/projects/{project_id}/auth/domains', 'Auth (legacy)', 'List trusted redirect URI domains', None, (), ()),
    'list_org_api_keys': ('GET', '/organizations/{org_id}/api_keys', 'Organizations', 'List organization API keys', None, (), ()),
    'list_organization_vpc_endpoints': ('GET', '/organizations/{org_id}/vpc/region/{region_id}/vpc_endpoints', 'Organizations', 'List VPC endpoints', None, (), ()),
    'list_organization_vpc_endpoints_all_regions': ('GET', '/organizations/{org_id}/vpc/vpc_endpoints', 'Organizations', 'List VPC endpoints across all regions', None, (), ()),
    'list_project_branch_bucket_objects': ('GET', '/projects/{project_id}/branches/{branch_id}/buckets/{bucket_name}/objects', 'Buckets', 'List objects in a bucket', None, (), ('cursor', 'delimiter', 'limit', 'prefix')),
    'list_project_branch_buckets': ('GET', '/projects/{project_id}/branches/{branch_id}/buckets', 'Buckets', 'List buckets on the branch', None, (), ()),
    'list_project_branch_custom_domains': ('GET', '/projects/{project_id}/branches/{branch_id}/custom-domains', 'Functions', 'List the custom domains on a branch', None, (), ('cursor', 'limit')),
    'list_project_branch_databases': ('GET', '/projects/{project_id}/branches/{branch_id}/databases', 'Branch', 'List databases', None, (), ()),
    'list_project_branch_endpoints': ('GET', '/projects/{project_id}/branches/{branch_id}/endpoints', 'Branch', 'List branch endpoints', None, (), ()),
    'list_project_branch_functions': ('GET', '/projects/{project_id}/branches/{branch_id}/functions', 'Functions', 'List functions on the branch', None, (), ('cursor', 'limit')),
    'list_project_branch_log_field_values': ('GET', '/projects/{project_id}/branches/{branch_id}/logs/fields/{field_name}/values', 'Logs', 'List branch log field values', None, (), ('end_time', 'limit', 'since', 'source', 'start_time')),
    'list_project_branch_log_fields': ('GET', '/projects/{project_id}/branches/{branch_id}/logs/fields', 'Logs', 'List branch log fields', None, (), ()),
    'list_project_branch_roles': ('GET', '/projects/{project_id}/branches/{branch_id}/roles', 'Branch', 'List roles', None, (), ()),
    'list_project_branch_triggers': ('GET', '/projects/{project_id}/branches/{branch_id}/triggers', 'Functions', 'List triggers on the branch', None, (), ()),
    'list_project_branches': ('GET', '/projects/{project_id}/branches', 'Branch', 'List branches', None, (), ('cursor', 'include_deleted', 'limit', 'search', 'sort_by', 'sort_order')),
    'list_project_endpoints': ('GET', '/projects/{project_id}/endpoints', 'Endpoint', 'List compute endpoints', None, (), ()),
    'list_project_members': ('GET', '/projects/{project_id}/members', 'Project', 'List org members and their project roles', None, (), ('cursor', 'limit')),
    'list_project_operations': ('GET', '/projects/{project_id}/operations', 'Operation', 'List operations', None, (), ('cursor', 'limit')),
    'list_project_permissions': ('GET', '/projects/{project_id}/permissions', 'Project', 'List project access', None, (), ()),
    'list_project_vpc_endpoints': ('GET', '/projects/{project_id}/vpc_endpoints', 'Project', 'List VPC endpoint restrictions', None, (), ()),
    'list_projects': ('GET', '/projects', 'Project', 'List projects', None, (), ('cursor', 'limit', 'org_id', 'recoverable', 'search', 'timeout')),
    'list_shared_projects': ('GET', '/projects/shared', 'Project', 'List shared projects', None, (), ('cursor', 'limit', 'search', 'timeout')),
    'list_snapshots': ('GET', '/projects/{project_id}/snapshots', 'Snapshot', 'List project snapshots', None, (), ()),
    'presign_project_branch_bucket_object': ('POST', '/projects/{project_id}/branches/{branch_id}/buckets/{bucket_name}/objects/{object_key}/presign', 'Buckets', 'Presign an upload or download for an object in a bucket', True, (), ()),
    'query_project_branch_logs': ('POST', '/projects/{project_id}/branches/{branch_id}/logs/query', 'Logs', 'Query branch logs', True, (), ()),
    'recover_project': ('POST', '/projects/{project_id}/recover', 'Project', 'Recover a deleted project', None, (), ()),
    'register_project_branch_custom_domain': ('POST', '/projects/{project_id}/branches/{branch_id}/custom-domains', 'Functions', 'Register a custom domain on a branch', True, (), ()),
    'remove_organization_member': ('DELETE', '/organizations/{org_id}/members/{member_id}', 'Organizations', 'Remove organization member', None, (), ()),
    'remove_project_member_role': ('DELETE', '/projects/{project_id}/members/{member_id}/role', 'Project', "Remove an org member's role on a project", None, (), ('confirm_self_lockout',)),
    'reset_project_branch_role_password': ('POST', '/projects/{project_id}/branches/{branch_id}/roles/{role_name}/reset_password', 'Branch', 'Reset role password', None, (), ()),
    'restart_project_endpoint': ('POST', '/projects/{project_id}/endpoints/{endpoint_id}/restart', 'Endpoint', 'Restart compute endpoint', None, (), ()),
    'restore_project_branch': ('POST', '/projects/{project_id}/branches/{branch_id}/restore', 'Branch', 'Restore branch to a historical state', True, (), ()),
    'restore_snapshot': ('POST', '/projects/{project_id}/snapshots/{snapshot_id}/restore', 'Snapshot', 'Restore snapshot', False, (), ('name',)),
    'reveal_credential': ('POST', '/projects/{project_id}/branches/{branch_id}/credentials/{token_id}/reveal', 'Credentials', "Reveal a credential's secrets", None, (), ()),
    'revoke_api_key': ('DELETE', '/api_keys/{key_id}', 'API Key', 'Revoke API key', None, (), ()),
    'revoke_credential': ('DELETE', '/projects/{project_id}/branches/{branch_id}/credentials/{token_id}', 'Credentials', 'Revoke a credential', None, (), ()),
    'revoke_org_api_key': ('DELETE', '/organizations/{org_id}/api_keys/{key_id}', 'Organizations', 'Revoke organization API key', None, (), ()),
    'revoke_permission_from_project': ('DELETE', '/projects/{project_id}/permissions/{permission_id}', 'Project', 'Revoke project access', None, (), ()),
    'rotate_credential': ('POST', '/projects/{project_id}/branches/{branch_id}/credentials/{token_id}/rotate', 'Credentials', "Rotate a credential's secrets", None, (), ()),
    'send_neon_auth_email_provider_test': ('POST', '/projects/{project_id}/branches/{branch_id}/auth/email_provider/test', 'Auth', 'Send test email using the saved email provider', True, (), ()),
    'send_neon_auth_test_email': ('POST', '/projects/{project_id}/branches/{branch_id}/auth/send_test_email', 'Auth', 'Send test email', True, (), ()),
    'set_default_project_branch': ('POST', '/projects/{project_id}/branches/{branch_id}/set_as_default', 'Branch', 'Set branch as default', None, (), ()),
    'set_organization_spending_limit': ('PUT', '/organizations/{org_id}/billing/spending_limit', 'Organizations', 'Set organization spending limit', True, (), ()),
    'set_project_member_role': ('PUT', '/projects/{project_id}/members/{member_id}/role', 'Project', "Set an org member's role on a project", True, (), ('confirm_self_demotion',)),
    'set_snapshot_schedule': ('PUT', '/projects/{project_id}/branches/{branch_id}/backup_schedule', 'Snapshot', 'Update backup schedule', True, (), ()),
    'start_anonymization': ('POST', '/projects/{project_id}/branches/{branch_id}/anonymize', 'Branch', 'Start anonymization', None, (), ()),
    'start_project_endpoint': ('POST', '/projects/{project_id}/endpoints/{endpoint_id}/start', 'Endpoint', 'Start compute endpoint', None, (), ()),
    'suspend_project_endpoint': ('POST', '/projects/{project_id}/endpoints/{endpoint_id}/suspend', 'Endpoint', 'Suspend compute endpoint', None, (), ()),
    'transfer_neon_auth_provider_project': ('POST', '/projects/auth/transfer_ownership', 'Auth (legacy)', 'Transfer Neon-managed auth project to your own account', True, (), ()),
    'transfer_projects_from_org_to_org': ('POST', '/organizations/{source_org_id}/projects/transfer', 'Organizations', 'Transfer projects between organizations', True, (), ()),
    'transfer_projects_from_user_to_org': ('POST', '/users/me/projects/transfer', 'Users', 'Transfer projects from personal account to organization', True, (), ()),
    'update_branch_neon_auth_oauth_provider': ('PATCH', '/projects/{project_id}/branches/{branch_id}/auth/oauth_providers/{oauth_provider_id}', 'Auth', 'Update OAuth provider', True, (), ()),
    'update_masking_rules': ('PATCH', '/projects/{project_id}/branches/{branch_id}/masking_rules', 'Branch', 'Update masking rules', True, (), ()),
    'update_neon_auth_allow_localhost': ('PATCH', '/projects/{project_id}/branches/{branch_id}/auth/allow_localhost', 'Auth', 'Update localhost allow setting', True, (), ()),
    'update_neon_auth_config': ('PATCH', '/projects/{project_id}/branches/{branch_id}/auth/config', 'Auth', 'Update auth configuration', True, (), ()),
    'update_neon_auth_email_and_password_config': ('PATCH', '/projects/{project_id}/branches/{branch_id}/auth/email_and_password', 'Auth', 'Update email and password configuration', True, (), ()),
    'update_neon_auth_email_provider': ('PATCH', '/projects/{project_id}/branches/{branch_id}/auth/email_provider', 'Auth', 'Update email provider configuration', True, (), ()),
    'update_neon_auth_email_server': ('PATCH', '/projects/{project_id}/auth/email_server', 'Auth (legacy)', 'Update email server configuration', True, (), ()),
    'update_neon_auth_magic_link_plugin': ('PATCH', '/projects/{project_id}/branches/{branch_id}/auth/plugins/magic-link', 'Auth', 'Update magic link plugin configuration', True, (), ()),
    'update_neon_auth_oauth_provider': ('PATCH', '/projects/{project_id}/auth/oauth_providers/{oauth_provider_id}', 'Auth (legacy)', 'Update OAuth provider', True, (), ()),
    'update_neon_auth_organization_plugin': ('PATCH', '/projects/{project_id}/branches/{branch_id}/auth/plugins/organization', 'Auth', 'Update organization plugin configuration', True, (), ()),
    'update_neon_auth_phone_number_plugin': ('PATCH', '/projects/{project_id}/branches/{branch_id}/auth/plugins/phone-number', 'Auth', 'Update phone number plugin configuration', True, (), ()),
    'update_neon_auth_user_role': ('PUT', '/projects/{project_id}/branches/{branch_id}/auth/users/{auth_user_id}/role', 'Auth', 'Update auth user role', True, (), ()),
    'update_neon_auth_webhook_config': ('PUT', '/projects/{project_id}/branches/{branch_id}/auth/webhooks', 'Auth', 'Update Neon Auth webhook configuration', True, (), ()),
    'update_organization_member': ('PATCH', '/organizations/{org_id}/members/{member_id}', 'Organizations', 'Update role for organization member', True, (), ()),
    'update_project': ('PATCH', '/projects/{project_id}', 'Project', 'Update project', True, (), ()),
    'update_project_branch': ('PATCH', '/projects/{project_id}/branches/{branch_id}', 'Branch', 'Update branch', True, (), ()),
    'update_project_branch_data_api': ('PATCH', '/projects/{project_id}/branches/{branch_id}/data-api/{database_name}', 'DataAPI', 'Update Neon Data API', False, (), ()),
    'update_project_branch_database': ('PATCH', '/projects/{project_id}/branches/{branch_id}/databases/{database_name}', 'Branch', 'Update database', True, (), ()),
    'update_project_branch_function': ('PATCH', '/projects/{project_id}/branches/{branch_id}/functions/{slug}', 'Functions', 'Update a function', True, (), ()),
    'update_project_branch_trigger': ('PATCH', '/projects/{project_id}/branches/{branch_id}/triggers/{trigger_id}', 'Functions', 'Update a trigger', True, (), ()),
    'update_project_endpoint': ('PATCH', '/projects/{project_id}/endpoints/{endpoint_id}', 'Endpoint', 'Update compute endpoint', True, (), ()),
    'update_snapshot': ('PATCH', '/projects/{project_id}/snapshots/{snapshot_id}', 'Snapshot', 'Update snapshot', True, (), ()),
}


def _title(name: str) -> str:
    return name.replace("_", " ").title().replace(" Id", " ID")


def _path_field(name: str):
    extra: Dict[str, Any] = {}
    if name == "project_id":
        extra["x-dynamic-options"] = {
            "field_name": "project_id", "searchable": True, "allow_custom": True,
            "placeholder": "Select project…", "custom_placeholder": "Or enter project ID",
        }
    elif name == "branch_id":
        extra["x-dynamic-options"] = {
            "field_name": "branch_id", "depends_on": "project_id", "searchable": True,
            "allow_custom": True, "placeholder": "Select branch…",
            "custom_placeholder": "Or enter branch ID",
        }
    return Field(..., title=_title(name), json_schema_extra=extra)


_operation_models = []
for _action, (_method, _path, _category, _label, _body_required, _required_query, _query_names) in NEON_ENDPOINTS.items():
    _fields: Dict[str, Any] = {
        "operation": (Literal[_action], Field(
            _action, title=_label,
            json_schema_extra={"const": _action, "ui:hidden": True,
                               "x-category": _category, "x-display-name": _label,
                               "x-is-trigger": False},
        )),
    }
    for _param in re.findall(r"\{([^}]+)\}", _path):
        _fields[_param] = (str, _path_field(_param))
    if _query_names:
        _fields["query_json"] = (str, Field(
            "{}", title="Query parameters (JSON)",
            description="Supported keys: " + ", ".join(_query_names),
            json_schema_extra={"ui:widget": "textarea"},
        ))
    if _action == "set_organization_spending_limit":
        _fields["spending_limit_cents"] = (int, Field(
            ..., gt=0, strict=True, title="Monthly spending threshold (cents)",
            description="Positive monthly threshold in cents; 10000 is $100.00. "
                        "Sends notifications at 80% and 100%; computes keep running. "
                        "Use Remove organization spending limit to clear the threshold.",
        ))
    elif _body_required is True:
        _fields["body_json"] = (str, Field(
            ..., title="Request body (JSON)",
            description="JSON body from Neon's API reference for this operation",
            json_schema_extra={"ui:widget": "textarea"},
        ))
    elif _body_required is False:
        _fields["body_json"] = (Optional[str], Field(
            None, title="Request body (JSON)",
            description="Optional JSON body from Neon's API reference",
            json_schema_extra={"ui:widget": "textarea"},
        ))
    _model_name = "Neon" + "".join(part.title() for part in _action.split("_")) + "Config"
    _model = create_model(_model_name, __module__=__name__, **_fields)
    globals()[_model_name] = _model
    _operation_models.append(_model)

NeonOperation = Annotated[Union[tuple(_operation_models)], Discriminator("operation")]


class NeonNodeConfig(NodeConfig[NeonOperation, NeonCredential]):
    pass


class NeonNode(WorkflowNode):
    """Manage Neon projects, branches, databases, computes and related APIs."""

    integration_type = "automation-neon"
    credential_provider_labels = {"neon": "Neon Account"}

    connection_evidence = ConnectionEvidence(
        field="project_id", identity_operation="get_current_user_info", noun="projects",
    )
    edit_examples = [
        "List my Neon projects and branches",
        "Create a database branch for this preview deployment",
        "Get the schema of my Neon development branch",
    ]

    @classmethod
    def get_config_model(cls):
        return NeonNodeConfig

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: Dict[str, Any],
                                 context: Optional[Dict[str, Any]] = None,
                                 page_token: Optional[str] = None,
                                 search: Optional[str] = None) -> Dict[str, Any]:
        key = credential_data.get("api_key")
        if not key:
            return {"options": []}
        if field_name == "project_id":
            path, collection, label = "/projects", "projects", "name"
        elif field_name == "branch_id" and (context or {}).get("project_id"):
            project_id = quote(str(context["project_id"]), safe="")
            path, collection, label = f"/projects/{project_id}/branches", "branches", "name"
        else:
            return {"options": []}
        params: Dict[str, Any] = {"limit": 100}
        if page_token:
            params["cursor"] = page_token
        if search:
            params["search"] = search
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(API_BASE + path,
                                        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                                        params=params)
        response.raise_for_status()
        data = response.json()
        options = [{"value": row["id"], "label": row.get(label) or row["id"]}
                   for row in data.get(collection, []) if isinstance(row, dict) and row.get("id")]
        pagination = data.get("pagination") or {}
        return {"options": options, "next_page_token": pagination.get("next")}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, NeonNodeConfig) or not self.config.credentials:
            raise ValueError("Neon API key credential is required")
        cfg = self.config.config
        action = cfg.operation
        method, path, _, _, body_required, required_query, _ = NEON_ENDPOINTS[action]
        for param in re.findall(r"\{([^}]+)\}", path):
            value = getattr(cfg, param)
            path = path.replace("{" + param + "}", quote(value, safe=""))

        def parse_object(value: Optional[str], name: str) -> Dict[str, Any]:
            if not value:
                return {}
            try:
                parsed = json.loads(value)
            except ValueError as exc:
                raise ValueError(f"{name} must be valid JSON") from exc
            if not isinstance(parsed, dict):
                raise ValueError(f"{name} must be a JSON object")
            return parsed

        query = parse_object(getattr(cfg, "query_json", None), "Query parameters")
        missing = set(required_query) - query.keys()
        if missing:
            raise ValueError("Required query parameters: " + ", ".join(sorted(missing)))
        raw_body = getattr(cfg, "body_json", None)
        body = parse_object(raw_body, "Request body") if raw_body else None
        if action == "set_organization_spending_limit":
            body = {"spending_limit_cents": cfg.spending_limit_cents}
        if body_required is True and not body:
            raise ValueError("Request body is required")

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method, API_BASE + path,
                    headers={"Authorization": f"Bearer {self.config.credentials.api_key}",
                             "Accept": "application/json"},
                    params=query or None, json=body,
                )
            elapsed = round((time.monotonic() - start) * 1000, 2)
            if response.status_code >= 400:
                # Provider errors can echo submitted bodies, SQL, or passwords.
                return {"status": "error", "action": action, "status_code": response.status_code,
                        "error": f"Neon returned HTTP {response.status_code}",
                        "timing_ms": {"api_request": elapsed}}
            try:
                data = {"success": True} if not response.content else response.json()
            except ValueError:
                return {"status": "error", "action": action, "status_code": response.status_code,
                        "error": "Neon returned a non-JSON response",
                        "timing_ms": {"api_request": elapsed}}
            if isinstance(data, list):
                data = {"items": data}
            return {"status": "success", "action": action, "status_code": response.status_code,
                    "data": data, "timing_ms": {"api_request": elapsed}}
        except httpx.RequestError:
            return {"status": "error", "action": action, "status_code": 503,
                    "error": "Neon request failed",
                    "timing_ms": {"api_request": round((time.monotonic() - start) * 1000, 2)}}
