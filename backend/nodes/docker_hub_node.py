"""Docker Hub API 2-beta workflow actions for repositories and organization administration."""

from __future__ import annotations

import json
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.binary_output import BinaryOutput


_BASE_URL = "https://hub.docker.com"
_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}
_catalog = {'source': 'https://docs.docker.com/reference/api/hub/latest.yaml',
 'source_sha256': '46c09f04fd8e7b3fe464c9b406a1bf8a0a6a164c87083f57ebbab64ccb7c8d3f',
 'operations': [{'name': 'post_v2_access_tokens',
                 'label': 'Create personal access token',
                 'category': 'Access Tokens',
                 'description': 'Creates and returns a personal access token.',
                 'method': 'POST',
                 'path': '/v2/access-tokens',
                 'path_params': [],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['token_label', 'scopes'],
                 'body_fields': ['expires_at', 'scopes', 'token_label'],
                 'auth': 'pat'},
                {'name': 'get_v2_access_tokens',
                 'label': 'List personal access tokens',
                 'category': 'Access Tokens',
                 'description': 'Returns a paginated list of personal access tokens.',
                 'method': 'GET',
                 'path': '/v2/access-tokens',
                 'path_params': [],
                 'query_fields': ['page', 'page_size'],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'patch_v2_access_tokens_by_uuid',
                 'label': 'Update personal access token',
                 'category': 'Access Tokens',
                 'description': 'Updates a personal access token partially. You can either update '
                                "the token's label or enable/disable it.",
                 'method': 'PATCH',
                 'path': '/v2/access-tokens/{uuid}',
                 'path_params': ['uuid'],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': [],
                 'body_fields': ['is_active', 'token_label'],
                 'auth': 'pat'},
                {'name': 'get_v2_access_tokens_by_uuid',
                 'label': 'Get personal access token',
                 'category': 'Access Tokens',
                 'description': 'Returns a personal access token by UUID.',
                 'method': 'GET',
                 'path': '/v2/access-tokens/{uuid}',
                 'path_params': ['uuid'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'delete_v2_access_tokens_by_uuid',
                 'label': 'Delete personal access token',
                 'category': 'Access Tokens',
                 'description': 'Deletes a personal access token permanently. This cannot be '
                                'undone.',
                 'method': 'DELETE',
                 'path': '/v2/access-tokens/{uuid}',
                 'path_params': ['uuid'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'audit_logs__list_audit_actions',
                 'label': 'List audit log actions',
                 'category': 'Audit Logs',
                 'description': 'List audit log actions for a namespace to be used as a filter for '
                                'querying audit log events.',
                 'method': 'GET',
                 'path': '/v2/auditlogs/{account}/actions',
                 'path_params': ['account'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'audit_logs__list_audit_logs',
                 'label': 'List audit log events',
                 'category': 'Audit Logs',
                 'description': 'List audit log events for a given namespace.',
                 'method': 'GET',
                 'path': '/v2/auditlogs/{account}',
                 'path_params': ['account'],
                 'query_fields': ['action', 'actor', 'from', 'name', 'page', 'page_size', 'to'],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'get_v2_orgs_by_name_settings',
                 'label': 'Get organization settings',
                 'category': 'Org Settings',
                 'description': 'Returns organization settings by name.',
                 'method': 'GET',
                 'path': '/v2/orgs/{name}/settings',
                 'path_params': ['name'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'put_v2_orgs_by_name_settings',
                 'label': 'Update organization settings',
                 'category': 'Org Settings',
                 'description': "Updates an organization's settings. Some settings are only used "
                                'when the organization is on a business subscription.',
                 'method': 'PUT',
                 'path': '/v2/orgs/{name}/settings',
                 'path_params': ['name'],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['restricted_images'],
                 'body_fields': ['restricted_images'],
                 'auth': 'pat'},
                {'name': 'post_v2_orgs_by_name_access_tokens',
                 'label': 'Create access token',
                 'category': 'Org Access Tokens',
                 'description': 'Create an access token for an organization.',
                 'method': 'POST',
                 'path': '/v2/orgs/{name}/access-tokens',
                 'path_params': ['name'],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['label', 'resources'],
                 'body_fields': ['description', 'expires_at', 'label', 'resources'],
                 'auth': 'pat'},
                {'name': 'get_v2_orgs_by_name_access_tokens',
                 'label': 'List access tokens',
                 'category': 'Org Access Tokens',
                 'description': 'List access tokens for an organization.',
                 'method': 'GET',
                 'path': '/v2/orgs/{name}/access-tokens',
                 'path_params': ['name'],
                 'query_fields': ['page', 'page_size'],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'get_v2_orgs_by_org_name_access_tokens_by_access_token_id',
                 'label': 'Get access token',
                 'category': 'Org Access Tokens',
                 'description': 'Get details of a specific access token for an organization.',
                 'method': 'GET',
                 'path': '/v2/orgs/{org_name}/access-tokens/{access_token_id}',
                 'path_params': ['org_name', 'access_token_id'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'patch_v2_orgs_by_org_name_access_tokens_by_access_token_id',
                 'label': 'Update access token',
                 'category': 'Org Access Tokens',
                 'description': 'Update a specific access token for an organization.',
                 'method': 'PATCH',
                 'path': '/v2/orgs/{org_name}/access-tokens/{access_token_id}',
                 'path_params': ['org_name', 'access_token_id'],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': [],
                 'body_fields': ['description', 'is_active', 'label', 'resources'],
                 'auth': 'pat'},
                {'name': 'delete_v2_orgs_by_org_name_access_tokens_by_access_token_id',
                 'label': 'Delete access token',
                 'category': 'Org Access Tokens',
                 'description': 'Delete a specific access token for an organization. This action '
                                'cannot be undone.',
                 'method': 'DELETE',
                 'path': '/v2/orgs/{org_name}/access-tokens/{access_token_id}',
                 'path_params': ['org_name', 'access_token_id'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'list_repository_tags',
                 'label': 'List repository tags',
                 'category': 'Repositories',
                 'description': 'Returns the list of tags for the specified repository.',
                 'method': 'GET',
                 'path': '/v2/namespaces/{namespace}/repositories/{repository}/tags',
                 'path_params': ['namespace', 'repository'],
                 'query_fields': ['page', 'page_size'],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'head_v2_namespaces_by_namespace_repositories_by_repository_tags',
                 'label': 'Check repository tags',
                 'category': 'Repositories',
                 'description': 'Checks whether the repository has any tags.',
                 'method': 'HEAD',
                 'path': '/v2/namespaces/{namespace}/repositories/{repository}/tags',
                 'path_params': ['namespace', 'repository'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'get_repository_tag',
                 'label': 'Read repository tag',
                 'category': 'Repositories',
                 'description': 'Returns details for a specific tag in the specified repository.',
                 'method': 'GET',
                 'path': '/v2/namespaces/{namespace}/repositories/{repository}/tags/{tag}',
                 'path_params': ['namespace', 'repository', 'tag'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'head_v2_namespaces_by_namespace_repositories_by_repository_tags_by_tag',
                 'label': 'Check repository tag',
                 'category': 'Repositories',
                 'description': 'Checks whether the specified tag exists in the repository.',
                 'method': 'HEAD',
                 'path': '/v2/namespaces/{namespace}/repositories/{repository}/tags/{tag}',
                 'path_params': ['namespace', 'repository', 'tag'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'update_repository_immutable_tags',
                 'label': 'Update repository immutable tags',
                 'category': 'Repositories',
                 'description': 'Updates the immutable tags configuration for this repository.',
                 'method': 'PATCH',
                 'path': '/v2/namespaces/{namespace}/repositories/{repository}/immutabletags',
                 'path_params': ['namespace', 'repository'],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['immutable_tags', 'immutable_tags_rules'],
                 'body_fields': ['immutable_tags', 'immutable_tags_rules'],
                 'auth': 'pat'},
                {'name': 'verify_repository_immutable_tags',
                 'label': 'Verify repository immutable tags',
                 'category': 'Repositories',
                 'description': 'Validates the immutable tags regex passed in the request body and '
                                'returns a list of tags matching it in this repository.',
                 'method': 'POST',
                 'path': '/v2/namespaces/{namespace}/repositories/{repository}/immutabletags/verify',
                 'path_params': ['namespace', 'repository'],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['regex'],
                 'body_fields': ['regex'],
                 'auth': 'pat'},
                {'name': 'create_repository_group',
                 'label': 'Assign a group (Team) to a repository for access',
                 'category': 'Repositories',
                 'description': 'Assigns an organization group (team) to a repository with a '
                                'specified permission level.',
                 'method': 'POST',
                 'path': '/v2/repositories/{namespace}/{repository}/groups',
                 'path_params': ['namespace', 'repository'],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['group_id', 'permission'],
                 'body_fields': ['group_id', 'permission'],
                 'auth': 'pat'},
                {'name': 'list_namespace_repositories',
                 'label': 'List repositories in a namespace',
                 'category': 'Repositories',
                 'description': 'Returns a list of repositories within the specified namespace '
                                '(organization or user).',
                 'method': 'GET',
                 'path': '/v2/namespaces/{namespace}/repositories',
                 'path_params': ['namespace'],
                 'query_fields': ['name', 'ordering', 'page', 'page_size'],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'create_repository',
                 'label': 'Create a new repository',
                 'category': 'Repositories',
                 'description': 'Creates a new repository within the specified namespace. The '
                                'repository will be created',
                 'method': 'POST',
                 'path': '/v2/namespaces/{namespace}/repositories',
                 'path_params': ['namespace'],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['name', 'namespace'],
                 'body_fields': ['description',
                                 'full_description',
                                 'is_private',
                                 'name',
                                 'namespace',
                                 'registry'],
                 'auth': 'pat'},
                {'name': 'get_repository',
                 'label': 'Get repository in a namespace',
                 'category': 'Repositories',
                 'description': 'Returns a repository within the specified namespace (organization '
                                'or user).',
                 'method': 'GET',
                 'path': '/v2/namespaces/{namespace}/repositories/{repository}',
                 'path_params': ['namespace', 'repository'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'check_repository',
                 'label': 'Check repository in a namespace',
                 'category': 'Repositories',
                 'description': 'Check a repository within the specified namespace (organization '
                                'or user).',
                 'method': 'HEAD',
                 'path': '/v2/namespaces/{namespace}/repositories/{repository}',
                 'path_params': ['namespace', 'repository'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'get_v2_orgs_by_org_name_members',
                 'label': 'List org members',
                 'category': 'Orgs',
                 'description': 'Returns a list of members for an organization.',
                 'method': 'GET',
                 'path': '/v2/orgs/{org_name}/members',
                 'path_params': ['org_name'],
                 'query_fields': ['invites', 'page', 'page_size', 'role', 'search', 'type'],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'get_v2_orgs_by_org_name_members_export',
                 'label': 'Export org members CSV',
                 'category': 'Orgs',
                 'description': 'Export members of an organization as a CSV',
                 'method': 'GET',
                 'path': '/v2/orgs/{org_name}/members/export',
                 'path_params': ['org_name'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'put_v2_orgs_by_org_name_members_by_username',
                 'label': 'Update org member (role)',
                 'category': 'Orgs',
                 'description': 'Updates the role of a member in the organization.',
                 'method': 'PUT',
                 'path': '/v2/orgs/{org_name}/members/{username}',
                 'path_params': ['org_name', 'username'],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['role'],
                 'body_fields': ['role'],
                 'auth': 'pat'},
                {'name': 'delete_v2_orgs_by_org_name_members_by_username',
                 'label': 'Remove member from org',
                 'category': 'Orgs',
                 'description': 'Removes the member from the org, ie. all groups in the org, '
                                "unless they're the last owner",
                 'method': 'DELETE',
                 'path': '/v2/orgs/{org_name}/members/{username}',
                 'path_params': ['org_name', 'username'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'get_v2_orgs_by_org_name_invites',
                 'label': 'List org invites',
                 'category': 'Invites',
                 'description': 'Return all pending invites for a given org, only team owners can '
                                'call this endpoint',
                 'method': 'GET',
                 'path': '/v2/orgs/{org_name}/invites',
                 'path_params': ['org_name'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'get_v2_orgs_by_org_name_groups',
                 'label': 'Get groups of an organization',
                 'category': 'Groups',
                 'description': 'Get groups of an organization.',
                 'method': 'GET',
                 'path': '/v2/orgs/{org_name}/groups',
                 'path_params': ['org_name'],
                 'query_fields': ['page', 'page_size', 'search', 'username'],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'post_v2_orgs_by_org_name_groups',
                 'label': 'Create a new group',
                 'category': 'Groups',
                 'description': 'Create a new group within an organization.',
                 'method': 'POST',
                 'path': '/v2/orgs/{org_name}/groups',
                 'path_params': ['org_name'],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': False,
                 'body_required_fields': ['name'],
                 'body_fields': ['description', 'name'],
                 'auth': 'pat'},
                {'name': 'get_v2_orgs_by_org_name_groups_by_group_name',
                 'label': 'Get a group of an organization',
                 'category': 'Groups',
                 'description': 'Get a group of an organization.',
                 'method': 'GET',
                 'path': '/v2/orgs/{org_name}/groups/{group_name}',
                 'path_params': ['org_name', 'group_name'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'put_v2_orgs_by_org_name_groups_by_group_name',
                 'label': 'Update the details for an organization group',
                 'category': 'Groups',
                 'description': 'Update the details for an organization group.',
                 'method': 'PUT',
                 'path': '/v2/orgs/{org_name}/groups/{group_name}',
                 'path_params': ['org_name', 'group_name'],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': False,
                 'body_required_fields': ['name'],
                 'body_fields': ['description', 'name'],
                 'auth': 'pat'},
                {'name': 'patch_v2_orgs_by_org_name_groups_by_group_name',
                 'label': 'Update some details for an organization group',
                 'category': 'Groups',
                 'description': 'Update some details for an organization group.',
                 'method': 'PATCH',
                 'path': '/v2/orgs/{org_name}/groups/{group_name}',
                 'path_params': ['org_name', 'group_name'],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': ['description', 'name', 'role'],
                 'auth': 'pat'},
                {'name': 'delete_v2_orgs_by_org_name_groups_by_group_name',
                 'label': 'Delete an organization group',
                 'category': 'Groups',
                 'description': 'Delete an organization group.',
                 'method': 'DELETE',
                 'path': '/v2/orgs/{org_name}/groups/{group_name}',
                 'path_params': ['org_name', 'group_name'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'get_v2_orgs_by_org_name_groups_by_group_name_members',
                 'label': 'List members of a group',
                 'category': 'Groups',
                 'description': 'List the members (users) that are in a group.',
                 'method': 'GET',
                 'path': '/v2/orgs/{org_name}/groups/{group_name}/members',
                 'path_params': ['org_name', 'group_name'],
                 'query_fields': ['page', 'page_size', 'search'],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'post_v2_orgs_by_org_name_groups_by_group_name_members',
                 'label': 'Add a member to a group',
                 'category': 'Groups',
                 'description': 'Add a member to a group.',
                 'method': 'POST',
                 'path': '/v2/orgs/{org_name}/groups/{group_name}/members',
                 'path_params': ['org_name', 'group_name'],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['member'],
                 'body_fields': ['member'],
                 'auth': 'pat'},
                {'name': 'delete_v2_orgs_by_org_name_groups_by_group_name_members_by_username',
                 'label': 'Remove a user from a group',
                 'category': 'Groups',
                 'description': 'Remove a user from a group.',
                 'method': 'DELETE',
                 'path': '/v2/orgs/{org_name}/groups/{group_name}/members/{username}',
                 'path_params': ['org_name', 'group_name', 'username'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'delete_v2_invites_by_id',
                 'label': 'Cancel an invite',
                 'category': 'Invites',
                 'description': "Mark the invite as cancelled so it doesn't show up on the list of "
                                'pending invites',
                 'method': 'DELETE',
                 'path': '/v2/invites/{id}',
                 'path_params': ['id'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'patch_v2_invites_by_id_resend',
                 'label': 'Resend an invite',
                 'category': 'Invites',
                 'description': 'Resend a pending invite to the user, any org owner can resend an '
                                'invite',
                 'method': 'PATCH',
                 'path': '/v2/invites/{id}/resend',
                 'path_params': ['id'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'pat'},
                {'name': 'post_v2_invites_bulk',
                 'label': 'Bulk create invites',
                 'category': 'Invites',
                 'description': 'Create multiple invites by emails or DockerIDs. Only a team owner '
                                'can create invites.',
                 'method': 'POST',
                 'path': '/v2/invites/bulk',
                 'path_params': [],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/json',
                 'body_required': True,
                 'body_required_fields': ['org', 'invitees'],
                 'body_fields': ['dry_run', 'invitees', 'org', 'role', 'team'],
                 'auth': 'pat'},
                {'name': 'get_v2_scim20_service_provider_config',
                 'label': 'Get service provider config',
                 'category': 'Scim',
                 'description': "Returns a service provider config for Docker's configuration.",
                 'method': 'GET',
                 'path': '/v2/scim/2.0/ServiceProviderConfig',
                 'path_params': [],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'scim'},
                {'name': 'get_v2_scim20_resource_types',
                 'label': 'List resource types',
                 'category': 'Scim',
                 'description': 'Returns all resource types supported for the SCIM configuration.',
                 'method': 'GET',
                 'path': '/v2/scim/2.0/ResourceTypes',
                 'path_params': [],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'scim'},
                {'name': 'get_v2_scim20_resource_types_by_name',
                 'label': 'Get a resource type',
                 'category': 'Scim',
                 'description': 'Returns a resource type by name.',
                 'method': 'GET',
                 'path': '/v2/scim/2.0/ResourceTypes/{name}',
                 'path_params': ['name'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'scim'},
                {'name': 'get_v2_scim20_schemas',
                 'label': 'List schemas',
                 'category': 'Scim',
                 'description': 'Returns all schemas supported for the SCIM configuration.',
                 'method': 'GET',
                 'path': '/v2/scim/2.0/Schemas',
                 'path_params': [],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'scim'},
                {'name': 'get_v2_scim20_schemas_by_id',
                 'label': 'Get a schema',
                 'category': 'Scim',
                 'description': 'Returns a schema by ID.',
                 'method': 'GET',
                 'path': '/v2/scim/2.0/Schemas/{id}',
                 'path_params': ['id'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'scim'},
                {'name': 'get_v2_scim20_users',
                 'label': 'List users',
                 'category': 'Scim',
                 'description': 'Returns paginated users for an organization. Use `startIndex` and '
                                '`count` query parameters to receive paginated results.',
                 'method': 'GET',
                 'path': '/v2/scim/2.0/Users',
                 'path_params': [],
                 'query_fields': ['attributes',
                                  'count',
                                  'filter',
                                  'sortBy',
                                  'sortOrder',
                                  'startIndex'],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'scim'},
                {'name': 'post_v2_scim20_users',
                 'label': 'Create user',
                 'category': 'Scim',
                 'description': 'Creates a user. If the user already exists by email, they are '
                                'assigned to the organization on the "company" team.',
                 'method': 'POST',
                 'path': '/v2/scim/2.0/Users',
                 'path_params': [],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/scim+json',
                 'body_required': True,
                 'body_required_fields': ['schemas', 'userName'],
                 'body_fields': ['name', 'schemas', 'userName'],
                 'auth': 'scim'},
                {'name': 'get_v2_scim20_users_by_id',
                 'label': 'Get a user',
                 'category': 'Scim',
                 'description': 'Returns a user by ID.',
                 'method': 'GET',
                 'path': '/v2/scim/2.0/Users/{id}',
                 'path_params': ['id'],
                 'query_fields': [],
                 'has_body': False,
                 'content_type': None,
                 'body_required': False,
                 'body_required_fields': [],
                 'body_fields': [],
                 'auth': 'scim'},
                {'name': 'put_v2_scim20_users_by_id',
                 'label': 'Update a user',
                 'category': 'Scim',
                 'description': "Updates a user. This route is used to change the user's name, "
                                'activate, and deactivate the user.',
                 'method': 'PUT',
                 'path': '/v2/scim/2.0/Users/{id}',
                 'path_params': ['id'],
                 'query_fields': [],
                 'has_body': True,
                 'content_type': 'application/scim+json',
                 'body_required': True,
                 'body_required_fields': ['schemas', 'userName'],
                 'body_fields': ['active', 'name', 'schemas', 'userName'],
                 'auth': 'scim'}]}
OPERATIONS: dict[str, dict[str, Any]] = {
    op["name"]: op for op in _catalog["operations"]
}
assert len(OPERATIONS) == len(_catalog["operations"]), "Duplicate Docker Hub action"
OPERATIONS["test_connection"] = {
    "name": "test_connection",
    "label": "Test Connection",
    "category": "Account",
    "description": "Confirm the token is accepted without exposing the resulting bearer token.",
    "method": "POST",
    "path": "/v2/auth/token",
    "path_params": [],
    "query_fields": [],
    "has_body": False,
    "body_required": False,
    "body_required_fields": [],
    "body_fields": [],
    "auth": "either",
}


class DockerHubPATCredential(BaseModel):
    """A Docker Hub username (or organization) and scoped access token."""

    credential_type: Literal["docker_hub_pat"] = Field(
        "docker_hub_pat", json_schema_extra={"ui:hidden": True}
    )
    identifier: str = Field(
        ...,
        title="Docker Hub Username or Organization",
        description="The username for a personal access token, or organization name for an organization access token.",
    )
    personal_access_token: str = Field(
        ...,
        title="Personal or Organization Access Token",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(
        title="Docker Hub Access Token",
        json_schema_extra={
            "x-credential-url": "https://app.docker.com/settings/personal-access-tokens",
            "x-credential-instructions": (
                "Create a scoped personal access token in Docker Hub Settings. "
                "Use the matching username. Organization owners may use an organization access token instead."
            ),
        }
    )


class DockerHubSCIMCredential(BaseModel):
    """An organization SCIM provisioning token for SCIM-only actions."""

    credential_type: Literal["docker_hub_scim"] = Field(
        "docker_hub_scim", json_schema_extra={"ui:hidden": True}
    )
    scim_token: str = Field(
        ...,
        title="SCIM Provisioning Token",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(
        title="Docker Hub SCIM Token",
        json_schema_extra={
            "x-credential-url": "https://app.docker.com/",
            "x-credential-instructions": "Configure SCIM provisioning for a Docker organization and copy its SCIM token.",
        }
    )


DockerHubCredential = Union[DockerHubPATCredential, DockerHubSCIMCredential]


def _path_field(raw: str) -> str:
    return "path_" + re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()


def _make_config(op: dict[str, Any]) -> type[BaseModel]:
    name = op["name"]
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (
            Literal[name],
            Field(
                name,
                title=op["label"],
                description=op["description"],
                json_schema_extra={
                    "const": name,
                    "ui:hidden": True,
                    "x-category": op["category"],
                    "x-display-name": op["label"],
                    "x-is-trigger": False,
                },
            ),
        ),
    }
    for raw in op["path_params"]:
        fields[_path_field(raw)] = (
            str,
            Field(..., title=raw.replace("_", " ").title()),
        )
    if op["query_fields"]:
        fields["query_json"] = (
            Optional[str],
            Field(
                None,
                title="Query Parameters (JSON)",
                description="Use Docker's exact names: "
                + ", ".join(op["query_fields"]),
                json_schema_extra=_JSON_EDITOR,
            ),
        )
    if op["has_body"]:
        hint = "JSON request body for this Docker Hub action."
        if op["body_required_fields"]:
            hint += " Required keys: " + ", ".join(op["body_required_fields"]) + "."
        if op["body_fields"]:
            hint += (
                " Supported keys include: " + ", ".join(op["body_fields"][:20]) + "."
            )
        fields["body_json"] = (
            str if op["body_required"] else Optional[str],
            Field(
                ... if op["body_required"] else None,
                title="Request Body (JSON)",
                description=hint,
                json_schema_extra=_JSON_EDITOR,
            ),
        )
    return create_model(
        "DockerHub" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        **fields,
    )


CONFIG_MODELS = {name: _make_config(op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
DockerHubConfig = Annotated[
    Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")
]


class DockerHubNodeConfig(NodeConfig[DockerHubConfig, DockerHubCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _json_value(raw: Optional[str], label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except ValueError as exc:
        raise ValueError(f"{label} must contain valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _redact(value: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value


def _redact_data(value: Any, secrets: list[str]) -> Any:
    """Keep vendor responses from persisting the credential or exchanged JWT."""
    if isinstance(value, str):
        return _redact(value, secrets)
    if isinstance(value, list):
        return [_redact_data(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact_data(item, secrets) for key, item in value.items()}
    return value


class DockerHubNode(WorkflowNode):
    """Execute a documented Docker Hub API action."""

    integration_type = "automation-docker-hub"
    credential_provider_labels = {"docker_hub": "Docker Hub"}

    connection_evidence = ConnectionEvidence(
        operation="test_connection", noun="account"
    )
    edit_examples = [
        "List repositories in my Docker Hub namespace",
        "List tags for an image",
        "Create a Docker Hub repository",
        "View organization members",
    ]

    @classmethod
    def get_config_model(cls):
        return DockerHubNodeConfig

    @staticmethod
    async def _request(
        credential: DockerHubCredential,
        name: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        op = OPERATIONS[name]
        auth = op["auth"]
        is_scim = isinstance(credential, DockerHubSCIMCredential)
        if auth == "scim" and not is_scim:
            raise ValueError(
                "This action requires a Docker Hub SCIM provisioning credential"
            )
        if auth == "pat" and is_scim:
            raise ValueError(
                "This action requires a Docker Hub personal or organization access token"
            )

        path = op["path"]
        query: dict[str, Any] = {}
        kwargs: dict[str, Any] = {}
        if name != "test_connection":
            for raw in op["path_params"]:
                value = values.pop(_path_field(raw), None)
                if value is None or str(value).strip() in {"", ".", ".."}:
                    raise ValueError(f"{raw} is required")
                path = path.replace("{" + raw + "}", quote(str(value), safe=""))
            query = _json_value(values.pop("query_json", None), "Query Parameters")
            unknown = set(query) - set(op["query_fields"])
            if unknown:
                raise ValueError(
                    "Unknown query parameters: " + ", ".join(sorted(unknown))
                )
            if op["has_body"]:
                raw_body = values.pop("body_json", None)
                if op["body_required"] and not raw_body:
                    raise ValueError("Request Body is required")
                if raw_body:
                    body = _json_value(raw_body, "Request Body")
                    missing = set(op["body_required_fields"]) - set(body)
                    if missing:
                        raise ValueError(
                            "Request Body is missing required keys: "
                            + ", ".join(sorted(missing))
                        )
                    kwargs["json"] = body

        started = time.monotonic()
        headers = {"Accept": "application/json"}
        secrets: list[str] = []
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            if is_scim:
                headers["Authorization"] = f"Bearer {credential.scim_token}"
                secrets.append(credential.scim_token)
            else:
                secrets.append(credential.personal_access_token)
                token_response = await client.post(
                    _BASE_URL + "/v2/auth/token",
                    json={
                        "identifier": credential.identifier,
                        "secret": credential.personal_access_token,
                    },
                    headers=headers,
                )
                if token_response.is_error or token_response.is_redirect:
                    raise ValueError(
                        "Docker Hub authentication failed "
                        + str(token_response.status_code)
                        + ": "
                        + _redact(token_response.text[:300], secrets)
                    )
                try:
                    bearer = token_response.json()["access_token"]
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(
                        "Docker Hub did not return an access token"
                    ) from exc
                secrets.append(bearer)
                headers["Authorization"] = f"Bearer {bearer}"
            if name == "test_connection":
                if is_scim:
                    response = await client.get(
                        _BASE_URL + "/v2/scim/2.0/ServiceProviderConfig",
                        headers=headers,
                    )
                    if response.is_error or response.is_redirect:
                        raise ValueError(
                            "Docker Hub SCIM connection failed "
                            + str(response.status_code)
                        )
                    identity = "SCIM organization"
                else:
                    identity = credential.identifier
                return {
                    "status": "success",
                    "operation": name,
                    "account": identity,
                    "timing_ms": {
                        "api_request": round((time.monotonic() - started) * 1000, 2)
                    },
                }

            if kwargs and op["content_type"] == "application/scim+json":
                headers["Content-Type"] = "application/scim+json"
            response = await client.request(
                op["method"],
                _BASE_URL + path,
                params=query or None,
                headers=headers,
                **kwargs,
            )
        if response.is_error or response.is_redirect:
            raise ValueError(
                "Docker Hub API error "
                + str(response.status_code)
                + ": "
                + _redact(response.text[:300], secrets)
            )
        if not response.content:
            data: Any = {}
        elif "json" in response.headers.get("content-type", ""):
            try:
                data = response.json()
            except ValueError as exc:
                raise ValueError("Docker Hub returned invalid JSON") from exc
        else:
            data = BinaryOutput(
                data=response.content,
                content_type=response.headers.get("content-type", "application/octet-stream"),
                filename="docker-hub-response",
            )
        return {
            "status": "success",
            "operation": name,
            "status_code": response.status_code,
            "data": _redact_data(data, secrets),
            "pagination": {
                k: response.headers[k]
                for k in ("link", "x-next-page")
                if k in response.headers
            }
            or None,
            "timing_ms": {"api_request": round((time.monotonic() - started) * 1000, 2)},
        }

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if (
            not isinstance(self.config, DockerHubNodeConfig)
            or not self.config.credentials
        ):
            raise ValueError("Connect Docker Hub before running this action")
        return await self._request(
            self.config.credentials,
            self.config.config.operation,
            self.config.config.model_dump(exclude_none=True),
        )
