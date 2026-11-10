"""Postman API workflow actions for collections, workspaces, specs, and more."""

import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
"""Postman API action catalog from the official Postman API reference.

Source: https://learning.postman.com/api-docs/api-reference/
Snapshot: 2026-09-30. Actions requiring an API key from the core workspace,
collection, API design, mock, monitor, environment and spec surfaces are listed.
Enterprise-only SCIM and billing actions are intentionally excluded.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    body_type: str
    docs_url: str
    accept: str = "application/json"

OPERATIONS: dict[str, Operation] = {
    'ap_is_add_api_collection': Operation('Add a collection', 'API Builder', 'POST', '/apis/{apiId}/collections', 'application/json', 'https://learning.postman.com/api-docs/api-reference/ap-is/add-api-collection', 'application/vnd.api.v10+json'),
    'ap_is_create_api': Operation('Create an API', 'API Builder', 'POST', '/apis', 'application/json', 'https://learning.postman.com/api-docs/api-reference/ap-is/create-api', 'application/vnd.api.v10+json'),
    'ap_is_create_api_collection_comment': Operation('Create a collection comment', 'API Builder', 'POST', '/apis/{apiId}/collections/{collectionId}/comments', 'application/json', 'https://learning.postman.com/api-docs/api-reference/ap-is/create-api-collection-comment'),
    'ap_is_create_api_comment': Operation('Create an API comment', 'API Builder', 'POST', '/apis/{apiId}/comments', 'application/json', 'https://learning.postman.com/api-docs/api-reference/ap-is/create-api-comment'),
    'ap_is_create_api_schema': Operation('Create a schema', 'API Builder', 'POST', '/apis/{apiId}/schemas', 'application/json', 'https://learning.postman.com/api-docs/api-reference/ap-is/create-api-schema', 'application/vnd.api.v10+json'),
    'ap_is_create_api_version': Operation('Create a version', 'API Builder', 'POST', '/apis/{apiId}/versions', 'application/json', 'https://learning.postman.com/api-docs/api-reference/ap-is/create-api-version', 'application/vnd.api.v10+json'),
    'ap_is_create_update_api_schema_file': Operation('Create or update a schema file', 'API Builder', 'PUT', '/apis/{apiId}/schemas/{schemaId}/files/{file-path}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/ap-is/create-update-api-schema-file', 'application/vnd.api.v10+json'),
    'ap_is_delete_api': Operation('Delete an API', 'API Builder', 'DELETE', '/apis/{apiId}', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/delete-api', 'application/vnd.api.v10+json'),
    'ap_is_delete_api_collection_comment': Operation("Delete a collection's comment", 'API Builder', 'DELETE', '/apis/{apiId}/collections/{collectionId}/comments/{commentId}', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/delete-api-collection-comment'),
    'ap_is_delete_api_comment': Operation("Delete an API's comment", 'API Builder', 'DELETE', '/apis/{apiId}/comments/{commentId}', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/delete-api-comment'),
    'ap_is_delete_api_schema_file': Operation('Delete a schema file', 'API Builder', 'DELETE', '/apis/{apiId}/schemas/{schemaId}/files/{file-path}', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/delete-api-schema-file', 'application/vnd.api.v10+json'),
    'ap_is_delete_api_version': Operation('Delete a version', 'API Builder', 'DELETE', '/apis/{apiId}/versions/{versionId}', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/delete-api-version', 'application/vnd.api.v10+json'),
    'ap_is_get_api': Operation('Get an API', 'API Builder', 'GET', '/apis/{apiId}', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/get-api', 'application/vnd.api.v10+json'),
    'ap_is_get_api_collection': Operation('Get a collection', 'API Builder', 'GET', '/apis/{apiId}/collections/{collectionId}', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/get-api-collection', 'application/vnd.api.v10+json'),
    'ap_is_get_api_collection_comments': Operation("Get a collection's comments", 'API Builder', 'GET', '/apis/{apiId}/collections/{collectionId}/comments', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/get-api-collection-comments'),
    'ap_is_get_api_comments': Operation("Get an API's comments", 'API Builder', 'GET', '/apis/{apiId}/comments', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/get-api-comments'),
    'ap_is_get_api_schema': Operation('Get a schema', 'API Builder', 'GET', '/apis/{apiId}/schemas/{schemaId}', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/get-api-schema', 'application/vnd.api.v10+json'),
    'ap_is_get_api_schema_file_contents': Operation('Get schema file contents', 'API Builder', 'GET', '/apis/{apiId}/schemas/{schemaId}/files/{file-path}', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/get-api-schema-file-contents', 'application/vnd.api.v10+json'),
    'ap_is_get_api_schema_files': Operation('Get schema files', 'API Builder', 'GET', '/apis/{apiId}/schemas/{schemaId}/files', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/get-api-schema-files', 'application/vnd.api.v10+json'),
    'ap_is_get_api_version': Operation('Get a version', 'API Builder', 'GET', '/apis/{apiId}/versions/{versionId}', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/get-api-version', 'application/vnd.api.v10+json'),
    'ap_is_get_api_versions': Operation('Get all versions', 'API Builder', 'GET', '/apis/{apiId}/versions', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/get-api-versions', 'application/vnd.api.v10+json'),
    'ap_is_get_apis': Operation('Get all APIs', 'API Builder', 'GET', '/apis', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/get-apis', 'application/vnd.api.v10+json'),
    'ap_is_get_status_of_an_async_api_task': Operation('Get status of an asynchronous task', 'API Builder', 'GET', '/apis/{apiId}/tasks/{taskId}', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/get-status-of-an-async-api-task', 'application/vnd.api.v10+json'),
    'ap_is_sync_collection_with_schema': Operation('Sync collection with schema', 'API Builder', 'PUT', '/apis/{apiId}/collections/{collectionId}/sync-with-schema-tasks', 'none', 'https://learning.postman.com/api-docs/api-reference/ap-is/sync-collection-with-schema', 'application/vnd.api.v10+json'),
    'ap_is_update_api': Operation('Update an API', 'API Builder', 'PUT', '/apis/{apiId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/ap-is/update-api', 'application/vnd.api.v10+json'),
    'ap_is_update_api_collection_comment': Operation("Update a collection's comment", 'API Builder', 'PUT', '/apis/{apiId}/collections/{collectionId}/comments/{commentId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/ap-is/update-api-collection-comment'),
    'ap_is_update_api_comment': Operation("Update an API's comment", 'API Builder', 'PUT', '/apis/{apiId}/comments/{commentId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/ap-is/update-api-comment'),
    'ap_is_update_api_version': Operation('Update a version', 'API Builder', 'PUT', '/apis/{apiId}/versions/{versionId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/ap-is/update-api-version', 'application/vnd.api.v10+json'),
    'collection_folders_create_folder_comment': Operation('Create a folder comment', 'Collection Folders', 'POST', '/collections/{collectionId}/folders/{folderId}/comments', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collection-folders/create-folder-comment'),
    'collection_folders_delete_folder_comment': Operation("Delete a folder's comment", 'Collection Folders', 'DELETE', '/collections/{collectionId}/folders/{folderId}/comments/{commentId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collection-folders/delete-folder-comment'),
    'collection_folders_get_folder_comments': Operation("Get a folder's comments", 'Collection Folders', 'GET', '/collections/{collectionId}/folders/{folderId}/comments', 'none', 'https://learning.postman.com/api-docs/api-reference/collection-folders/get-folder-comments'),
    'collection_folders_update_folder_comment': Operation("Update a folder's comment", 'Collection Folders', 'PUT', '/collections/{collectionId}/folders/{folderId}/comments/{commentId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collection-folders/update-folder-comment'),
    'collection_items_create_collection_folder': Operation('Create a folder', 'Collection Items', 'POST', '/collections/{collectionId}/folders', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collection-items/create-collection-folder'),
    'collection_items_create_collection_request': Operation('Create a request', 'Collection Items', 'POST', '/collections/{collectionId}/requests', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collection-items/create-collection-request'),
    'collection_items_create_collection_response': Operation('Create a response', 'Collection Items', 'POST', '/collections/{collectionId}/responses', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collection-items/create-collection-response'),
    'collection_items_delete_collection_folder': Operation('Delete a folder', 'Collection Items', 'DELETE', '/collections/{collectionId}/folders/{folderId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collection-items/delete-collection-folder'),
    'collection_items_delete_collection_request': Operation('Delete a request', 'Collection Items', 'DELETE', '/collections/{collectionId}/requests/{requestId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collection-items/delete-collection-request'),
    'collection_items_delete_collection_response': Operation('Delete a response', 'Collection Items', 'DELETE', '/collections/{collectionId}/responses/{responseId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collection-items/delete-collection-response'),
    'collection_items_get_collection_folder': Operation('Get a folder', 'Collection Items', 'GET', '/collections/{collectionId}/folders/{folderId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collection-items/get-collection-folder'),
    'collection_items_get_collection_request': Operation('Get a request', 'Collection Items', 'GET', '/collections/{collectionId}/requests/{requestId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collection-items/get-collection-request'),
    'collection_items_get_collection_response': Operation('Get a response', 'Collection Items', 'GET', '/collections/{collectionId}/responses/{responseId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collection-items/get-collection-response'),
    'collection_items_update_collection_folder': Operation('Update a folder', 'Collection Items', 'PUT', '/collections/{collectionId}/folders/{folderId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collection-items/update-collection-folder'),
    'collection_items_update_collection_request': Operation('Update a request', 'Collection Items', 'PUT', '/collections/{collectionId}/requests/{requestId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collection-items/update-collection-request'),
    'collection_items_update_collection_response': Operation('Update a response', 'Collection Items', 'PUT', '/collections/{collectionId}/responses/{responseId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collection-items/update-collection-response'),
    'collection_requests_create_request_comment': Operation('Create a request comment', 'Collection Requests', 'POST', '/collections/{collectionId}/requests/{requestId}/comments', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collection-requests/create-request-comment'),
    'collection_requests_delete_request_comment': Operation("Delete a request's comment", 'Collection Requests', 'DELETE', '/collections/{collectionId}/requests/{requestId}/comments/{commentId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collection-requests/delete-request-comment'),
    'collection_requests_get_request_comments': Operation("Get a request's comments", 'Collection Requests', 'GET', '/collections/{collectionId}/requests/{requestId}/comments', 'none', 'https://learning.postman.com/api-docs/api-reference/collection-requests/get-request-comments'),
    'collection_requests_update_request_comment': Operation("Update a request's comment", 'Collection Requests', 'PUT', '/collections/{collectionId}/requests/{requestId}/comments/{commentId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collection-requests/update-request-comment'),
    'collection_responses_create_response_comment': Operation('Create a response comment', 'Collection Responses', 'POST', '/collections/{collectionId}/responses/{responseId}/comments', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collection-responses/create-response-comment'),
    'collection_responses_delete_response_comment': Operation("Delete a response's comment", 'Collection Responses', 'DELETE', '/collections/{collectionId}/responses/{responseId}/comments/{commentId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collection-responses/delete-response-comment'),
    'collection_responses_get_response_comments': Operation("Get a response's comments", 'Collection Responses', 'GET', '/collections/{collectionId}/responses/{responseId}/comments', 'none', 'https://learning.postman.com/api-docs/api-reference/collection-responses/get-response-comments'),
    'collection_responses_update_response_comment': Operation("Update a response's comment", 'Collection Responses', 'PUT', '/collections/{collectionId}/responses/{responseId}/comments/{commentId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collection-responses/update-response-comment'),
    'collections_async_merge_pull_collection_fork': Operation('Merge or pull changes into a collection fork', 'Collections', 'PUT', '/collection-merges', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/async-merge-pull-collection-fork'),
    'collections_async_merge_pull_collection_task_status': Operation('Get merge or pull task status', 'Collections', 'GET', '/collection-merges-tasks/{taskId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/async-merge-pull-collection-task-status'),
    'collections_create_collection': Operation('Create a collection', 'Collections', 'POST', '/collections', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/create-collection'),
    'collections_create_collection_comment': Operation('Create a collection comment', 'Collections', 'POST', '/collections/{collectionId}/comments', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/create-collection-comment'),
    'collections_create_collection_fork': Operation('Create a fork', 'Collections', 'POST', '/collections/fork/{collectionId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/create-collection-fork'),
    'collections_create_collection_pull_request': Operation('Create a pull request', 'Collections', 'POST', '/collections/{collectionId}/pull-requests', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/create-collection-pull-request'),
    'collections_delete_collection': Operation('Delete a collection', 'Collections', 'DELETE', '/collections/{collectionId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/delete-collection'),
    'collections_delete_collection_comment': Operation("Delete a collection's comment", 'Collections', 'DELETE', '/collections/{collectionId}/comments/{commentId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/delete-collection-comment'),
    'collections_duplicate_collection': Operation('Duplicate a collection', 'Collections', 'POST', '/collections/{collectionId}/duplicates', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/duplicate-collection'),
    'collections_get_collection': Operation('Get a collection', 'Collections', 'GET', '/collections/{collectionId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/get-collection'),
    'collections_get_collection_comments': Operation("Get a collection's comments", 'Collections', 'GET', '/collections/{collectionId}/comments', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/get-collection-comments'),
    'collections_get_collection_forks': Operation("Get a collection's forks", 'Collections', 'GET', '/collections/{collectionId}/forks', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/get-collection-forks'),
    'collections_get_collection_pull_requests': Operation("Get a collection's pull requests", 'Collections', 'GET', '/collections/{collectionId}/pull-requests', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/get-collection-pull-requests'),
    'collections_get_collection_roles': Operation("Get a collection's roles", 'Collections', 'GET', '/collections/{collectionId}/roles', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/get-collection-roles'),
    'collections_get_collection_updates_tasks': Operation('Get async collection update status', 'Collections', 'GET', '/collection-updates-tasks/{taskId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/get-collection-updates-tasks'),
    'collections_get_collections': Operation('Get all collections', 'Collections', 'GET', '/collections', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/get-collections'),
    'collections_get_collections_forked_by_user': Operation('Get all forked collections', 'Collections', 'GET', '/collections/collection-forks', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/get-collections-forked-by-user'),
    'collections_get_duplicate_collection_task_status': Operation('Get duplication task status', 'Collections', 'GET', '/collection-duplicate-tasks/{taskId}', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/get-duplicate-collection-task-status'),
    'collections_get_source_collection_status': Operation("Get source collection's status", 'Collections', 'GET', '/collections/{collectionId}/source-status', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/get-source-collection-status'),
    'collections_merge_collection_fork': Operation('Merge a fork', 'Collections', 'POST', '/collections/merge', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/merge-collection-fork'),
    'collections_patch_collection': Operation('Update part of a collection', 'Collections', 'PATCH', '/collections/{collectionId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/patch-collection'),
    'collections_publish_documentation': Operation('Publish documentation', 'Collections', 'PUT', '/collections/{collectionId}/public-documentations', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/publish-documentation'),
    'collections_pull_collection_changes': Operation('Pull source changes', 'Collections', 'PUT', '/collections/{collectionId}/pulls', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/pull-collection-changes'),
    'collections_put_collection': Operation("Replace a collection's data", 'Collections', 'PUT', '/collections/{collectionId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/put-collection'),
    'collections_transfer_collection_folders': Operation('Transfer folders', 'Collections', 'POST', '/collection-folders-transfers', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/transfer-collection-folders'),
    'collections_transfer_collection_requests': Operation('Transfer requests', 'Collections', 'POST', '/collection-requests-transfers', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/transfer-collection-requests'),
    'collections_transfer_collection_responses': Operation('Transfer responses', 'Collections', 'POST', '/collection-responses-transfers', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/transfer-collection-responses'),
    'collections_transform_collection_to_open_api': Operation('Transform collection to OpenAPI', 'Collections', 'GET', '/collections/{collectionId}/transformations', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/transform-collection-to-open-api'),
    'collections_unpublish_documentation': Operation('Unpublish documentation', 'Collections', 'DELETE', '/collections/{collectionId}/public-documentations', 'none', 'https://learning.postman.com/api-docs/api-reference/collections/unpublish-documentation'),
    'collections_update_collection_comment': Operation("Update a collection's comment", 'Collections', 'PUT', '/collections/{collectionId}/comments/{commentId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/update-collection-comment'),
    'collections_update_collection_roles': Operation("Update a collection's roles", 'Collections', 'PATCH', '/collections/{collectionId}/roles', 'application/json', 'https://learning.postman.com/api-docs/api-reference/collections/update-collection-roles'),
    'environments_create_environment': Operation('Create an environment', 'Environments', 'POST', '/environments', 'application/json', 'https://learning.postman.com/api-docs/api-reference/environments/create-environment'),
    'environments_delete_environment': Operation('Delete an environment', 'Environments', 'DELETE', '/environments/{environmentId}', 'none', 'https://learning.postman.com/api-docs/api-reference/environments/delete-environment'),
    'environments_fork_environment': Operation('Create a fork', 'Environments', 'POST', '/environments/{environmentId}/forks', 'application/json', 'https://learning.postman.com/api-docs/api-reference/environments/fork-environment'),
    'environments_get_environment': Operation('Get an environment', 'Environments', 'GET', '/environments/{environmentId}', 'none', 'https://learning.postman.com/api-docs/api-reference/environments/get-environment'),
    'environments_get_environment_forks': Operation("Get an environment's forks", 'Environments', 'GET', '/environments/{environmentId}/forks', 'none', 'https://learning.postman.com/api-docs/api-reference/environments/get-environment-forks'),
    'environments_get_environments': Operation('Get all environments', 'Environments', 'GET', '/environments', 'none', 'https://learning.postman.com/api-docs/api-reference/environments/get-environments'),
    'environments_merge_environment_fork': Operation('Merge a fork', 'Environments', 'POST', '/environments/{environmentId}/merges', 'application/json', 'https://learning.postman.com/api-docs/api-reference/environments/merge-environment-fork'),
    'environments_patch_environment': Operation('Update an environment', 'Environments', 'PATCH', '/environments/{environmentId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/environments/patch-environment'),
    'environments_pull_environment': Operation('Pull source changes', 'Environments', 'POST', '/environments/{environmentUid}/pulls', 'application/json', 'https://learning.postman.com/api-docs/api-reference/environments/pull-environment'),
    'environments_put_environment': Operation("Replace an environment's data", 'Environments', 'PUT', '/environments/{environmentId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/environments/put-environment'),
    'import_open_api_definition': Operation('Import an OpenAPI definition', 'Import', 'POST', '/import/openapi', 'application/json', 'https://learning.postman.com/api-docs/api-reference/import/open-api-definition'),
    'mocks_create_mock': Operation('Create a mock server', 'Mock Servers', 'POST', '/mocks', 'application/json', 'https://learning.postman.com/api-docs/api-reference/mocks/create-mock'),
    'mocks_create_mock_server_response': Operation('Create a server response', 'Mock Servers', 'POST', '/mocks/{mockId}/server-responses', 'application/json', 'https://learning.postman.com/api-docs/api-reference/mocks/create-mock-server-response'),
    'mocks_delete_mock': Operation('Delete a mock server', 'Mock Servers', 'DELETE', '/mocks/{mockId}', 'none', 'https://learning.postman.com/api-docs/api-reference/mocks/delete-mock'),
    'mocks_delete_mock_server_response': Operation('Delete a server response', 'Mock Servers', 'DELETE', '/mocks/{mockId}/server-responses/{serverResponseId}', 'none', 'https://learning.postman.com/api-docs/api-reference/mocks/delete-mock-server-response'),
    'mocks_get_mock': Operation('Get a mock server', 'Mock Servers', 'GET', '/mocks/{mockId}', 'none', 'https://learning.postman.com/api-docs/api-reference/mocks/get-mock'),
    'mocks_get_mock_call_logs': Operation("Get a mock server's call logs", 'Mock Servers', 'GET', '/mocks/{mockId}/call-logs', 'none', 'https://learning.postman.com/api-docs/api-reference/mocks/get-mock-call-logs'),
    'mocks_get_mock_server_response': Operation('Get a server response', 'Mock Servers', 'GET', '/mocks/{mockId}/server-responses/{serverResponseId}', 'none', 'https://learning.postman.com/api-docs/api-reference/mocks/get-mock-server-response'),
    'mocks_get_mock_server_responses': Operation('Get all server responses', 'Mock Servers', 'GET', '/mocks/{mockId}/server-responses', 'none', 'https://learning.postman.com/api-docs/api-reference/mocks/get-mock-server-responses'),
    'mocks_get_mocks': Operation('Get all mock servers', 'Mock Servers', 'GET', '/mocks', 'none', 'https://learning.postman.com/api-docs/api-reference/mocks/get-mocks'),
    'mocks_publish_mock': Operation('Publish a mock server', 'Mock Servers', 'POST', '/mocks/{mockId}/publish', 'none', 'https://learning.postman.com/api-docs/api-reference/mocks/publish-mock'),
    'mocks_unpublish_mock': Operation('Unpublish a mock server', 'Mock Servers', 'DELETE', '/mocks/{mockId}/unpublish', 'none', 'https://learning.postman.com/api-docs/api-reference/mocks/unpublish-mock'),
    'mocks_update_mock': Operation('Update a mock server', 'Mock Servers', 'PUT', '/mocks/{mockId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/mocks/update-mock'),
    'mocks_update_mock_server_response': Operation('Update a server response', 'Mock Servers', 'PUT', '/mocks/{mockId}/server-responses/{serverResponseId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/mocks/update-mock-server-response'),
    'monitors_create_monitor': Operation('Create a monitor', 'Monitors', 'POST', '/monitors', 'application/json', 'https://learning.postman.com/api-docs/api-reference/monitors/create-monitor'),
    'monitors_delete_monitor': Operation('Delete a monitor', 'Monitors', 'DELETE', '/monitors/{monitorId}', 'none', 'https://learning.postman.com/api-docs/api-reference/monitors/delete-monitor'),
    'monitors_get_monitor': Operation('Get a monitor', 'Monitors', 'GET', '/monitors/{monitorId}', 'none', 'https://learning.postman.com/api-docs/api-reference/monitors/get-monitor'),
    'monitors_get_monitors': Operation('Get all monitors', 'Monitors', 'GET', '/monitors', 'none', 'https://learning.postman.com/api-docs/api-reference/monitors/get-monitors'),
    'monitors_get_runner_instances': Operation('Get all runner instances', 'Monitors', 'GET', '/runners/{runnerId}/instances', 'none', 'https://learning.postman.com/api-docs/api-reference/monitors/get-runner-instances'),
    'monitors_get_runner_metrics': Operation('Get runner metrics', 'Monitors', 'GET', '/runners/{runnerId}/metrics', 'none', 'https://learning.postman.com/api-docs/api-reference/monitors/get-runner-metrics'),
    'monitors_run_monitor': Operation('Run a monitor', 'Monitors', 'POST', '/monitors/{monitorId}/run', 'none', 'https://learning.postman.com/api-docs/api-reference/monitors/run-monitor'),
    'monitors_update_monitor': Operation('Update a monitor', 'Monitors', 'PUT', '/monitors/{monitorId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/monitors/update-monitor'),
    'pull_requests_get_pull_request': Operation('Get a pull request', 'Pull Requests', 'GET', '/pull-requests/{pullRequestId}', 'none', 'https://learning.postman.com/api-docs/api-reference/pull-requests/get-pull-request'),
    'pull_requests_review_pull_request': Operation('Review a pull request', 'Pull Requests', 'POST', '/pull-requests/{pullRequestId}/tasks', 'application/json', 'https://learning.postman.com/api-docs/api-reference/pull-requests/review-pull-request'),
    'pull_requests_update_pull_request': Operation('Update a pull request', 'Pull Requests', 'PUT', '/pull-requests/{pullRequestId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/pull-requests/update-pull-request'),
    'search_postman_resources': Operation('Search Postman resources', 'Search', 'POST', '/search', 'application/json', 'https://learning.postman.com/api-docs/api-reference/search/postman-resources'),
    'specs_create_spec': Operation('Create a spec', 'Spec Hub', 'POST', '/specs', 'application/json', 'https://learning.postman.com/api-docs/api-reference/specs/create-spec'),
    'specs_create_spec_file': Operation('Create a spec file', 'Spec Hub', 'POST', '/specs/{specId}/files', 'application/json', 'https://learning.postman.com/api-docs/api-reference/specs/create-spec-file'),
    'specs_create_spec_version_tag': Operation('Create a version tag', 'Spec Hub', 'POST', '/specs/{specId}/version-tags', 'application/json', 'https://learning.postman.com/api-docs/api-reference/specs/create-spec-version-tag'),
    'specs_delete_spec': Operation('Delete a spec', 'Spec Hub', 'DELETE', '/specs/{specId}', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/delete-spec'),
    'specs_delete_spec_file': Operation('Delete a spec file', 'Spec Hub', 'DELETE', '/specs/{specId}/files/{filePath}', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/delete-spec-file'),
    'specs_generate_collection': Operation('Generate a collection from spec', 'Spec Hub', 'POST', '/specs/{specId}/generations/{elementType}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/specs/generate-collection'),
    'specs_generate_spec_from_collection': Operation('Generate spec from collection', 'Spec Hub', 'POST', '/collections/{collectionUid}/generations/{elementType}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/specs/generate-spec-from-collection'),
    'specs_get_all_specs': Operation('Get all specs', 'Spec Hub', 'GET', '/specs', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/get-all-specs'),
    'specs_get_async_spec_task_status': Operation('Get status of an async spec task', 'Spec Hub', 'GET', '/{elementType}/{elementId}/tasks/{taskId}', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/get-async-spec-task-status'),
    'specs_get_generated_collection_specs': Operation('Get generated spec', 'Spec Hub', 'GET', '/collections/{collectionUid}/generations/{elementType}', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/get-generated-collection-specs'),
    'specs_get_migration_status': Operation('Get status of API Builder to Spec Hub migration', 'Spec Hub', 'GET', '/apis/{apiId}/spec-migrations', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/get-migration-status', 'application/vnd.api.v10+json'),
    'specs_get_spec': Operation('Get a spec', 'Spec Hub', 'GET', '/specs/{specId}', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/get-spec'),
    'specs_get_spec_collections': Operation("Get a spec's generated collections", 'Spec Hub', 'GET', '/specs/{specId}/generations/{elementType}', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/get-spec-collections'),
    'specs_get_spec_definition': Operation("Get a spec's definition", 'Spec Hub', 'GET', '/specs/{specId}/definitions', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/get-spec-definition'),
    'specs_get_spec_file': Operation('Get a spec file', 'Spec Hub', 'GET', '/specs/{specId}/files/{filePath}', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/get-spec-file'),
    'specs_get_spec_files': Operation("Get a spec's files", 'Spec Hub', 'GET', '/specs/{specId}/files', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/get-spec-files'),
    'specs_get_spec_version_tag': Operation('Get a version tag', 'Spec Hub', 'GET', '/specs/{specId}/version-tags/{tagId}/files', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/get-spec-version-tag'),
    'specs_get_spec_version_tags': Operation("Get a specification's version tags", 'Spec Hub', 'GET', '/specs/{specId}/version-tags', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/get-spec-version-tags'),
    'specs_migrate_api_to_spec_hub': Operation('Migrate API Builder API to Spec Hub', 'Spec Hub', 'POST', '/apis/{apiId}/spec-migrations', 'application/json', 'https://learning.postman.com/api-docs/api-reference/specs/migrate-api-to-spec-hub', 'application/vnd.api.v10+json'),
    'specs_sync_collection_with_spec': Operation('Sync collection with spec', 'Spec Hub', 'PUT', '/collections/{collectionUid}/synchronizations', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/sync-collection-with-spec'),
    'specs_sync_spec_with_collection': Operation('Sync spec with collection', 'Spec Hub', 'PUT', '/specs/{specId}/synchronizations', 'none', 'https://learning.postman.com/api-docs/api-reference/specs/sync-spec-with-collection'),
    'specs_update_spec_file': Operation('Update a spec file', 'Spec Hub', 'PATCH', '/specs/{specId}/files/{filePath}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/specs/update-spec-file'),
    'specs_update_spec_properties': Operation("Update a spec's properties", 'Spec Hub', 'PATCH', '/specs/{specId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/specs/update-spec-properties'),
    'specs_update_spec_sync_options': Operation('Update spec sync options', 'Spec Hub', 'PATCH', '/specs/{specId}/collections/{collectionId}/sync-options', 'application/json', 'https://learning.postman.com/api-docs/api-reference/specs/update-spec-sync-options'),
    'tags_get_api_tags': Operation("Get an API's tags", 'Tags', 'GET', '/apis/{apiId}/tags', 'none', 'https://learning.postman.com/api-docs/api-reference/tags/get-api-tags', 'application/vnd.api.v10+json'),
    'tags_get_collection_tags': Operation("Get a collection's tags", 'Tags', 'GET', '/collections/{collectionId}/tags', 'none', 'https://learning.postman.com/api-docs/api-reference/tags/get-collection-tags'),
    'tags_get_tagged_entities': Operation('Get elements by tag', 'Tags', 'GET', '/tags/{slug}/entities', 'none', 'https://learning.postman.com/api-docs/api-reference/tags/get-tagged-entities'),
    'tags_get_workspace_tags': Operation("Get a workspace's tags", 'Tags', 'GET', '/workspaces/{workspaceId}/tags', 'none', 'https://learning.postman.com/api-docs/api-reference/tags/get-workspace-tags'),
    'tags_update_api_tags': Operation("Update an API's tags", 'Tags', 'PUT', '/apis/{apiId}/tags', 'application/json', 'https://learning.postman.com/api-docs/api-reference/tags/update-api-tags', 'application/vnd.api.v10+json'),
    'tags_update_collection_tags': Operation("Update a collection's tags", 'Tags', 'PUT', '/collections/{collectionId}/tags', 'application/json', 'https://learning.postman.com/api-docs/api-reference/tags/update-collection-tags'),
    'tags_update_workspace_tags': Operation("Update a workspace's tags", 'Tags', 'PUT', '/workspaces/{workspaceId}/tags', 'application/json', 'https://learning.postman.com/api-docs/api-reference/tags/update-workspace-tags'),
    'get_authenticated_user': Operation('Get authenticated user', 'Users', 'GET', '/me', 'none', 'https://learning.postman.com/api-docs/api-reference/users/get-authenticated-user'),
    'users_get_team_user': Operation('Get a team user', 'Users', 'GET', '/users/{userId}', 'none', 'https://learning.postman.com/api-docs/api-reference/users/get-team-user'),
    'users_get_team_users': Operation('Get all team users', 'Users', 'GET', '/users', 'none', 'https://learning.postman.com/api-docs/api-reference/users/get-team-users'),
    'webhooks_create_webhook': Operation('Create a webhook', 'Webhooks', 'POST', '/webhooks', 'application/json', 'https://learning.postman.com/api-docs/api-reference/webhooks/create-webhook'),
    'workspaces_create_workspace': Operation('Create a workspace', 'Workspaces', 'POST', '/workspaces', 'application/json', 'https://learning.postman.com/api-docs/api-reference/workspaces/create-workspace'),
    'workspaces_create_workspace_update': Operation('Create a workspace update', 'Workspaces', 'POST', '/workspaces/{workspaceId}/updates', 'application/json', 'https://learning.postman.com/api-docs/api-reference/workspaces/create-workspace-update'),
    'workspaces_delete_workspace': Operation('Delete a workspace', 'Workspaces', 'DELETE', '/workspaces/{workspaceId}', 'none', 'https://learning.postman.com/api-docs/api-reference/workspaces/delete-workspace'),
    'workspaces_delete_workspace_update': Operation('Delete a workspace update', 'Workspaces', 'DELETE', '/workspaces/{workspaceId}/updates/{updateId}', 'none', 'https://learning.postman.com/api-docs/api-reference/workspaces/delete-workspace-update'),
    'workspaces_get_all_workspace_roles': Operation('Get all roles', 'Workspaces', 'GET', '/workspaces-roles', 'none', 'https://learning.postman.com/api-docs/api-reference/workspaces/get-all-workspace-roles'),
    'workspaces_get_workspace': Operation('Get a workspace', 'Workspaces', 'GET', '/workspaces/{workspaceId}', 'none', 'https://learning.postman.com/api-docs/api-reference/workspaces/get-workspace'),
    'workspaces_get_workspace_activity_feed': Operation("Get a workspace's activity feed", 'Workspaces', 'GET', '/workspaces/{workspaceId}/activities', 'none', 'https://learning.postman.com/api-docs/api-reference/workspaces/get-workspace-activity-feed'),
    'workspaces_get_workspace_global_variables': Operation('Get global variables', 'Workspaces', 'GET', '/workspaces/{workspaceId}/global-variables', 'none', 'https://learning.postman.com/api-docs/api-reference/workspaces/get-workspace-global-variables'),
    'workspaces_get_workspace_roles': Operation("Get a workspace's roles", 'Workspaces', 'GET', '/workspaces/{workspaceId}/roles', 'none', 'https://learning.postman.com/api-docs/api-reference/workspaces/get-workspace-roles'),
    'workspaces_get_workspace_update': Operation('Get a workspace update', 'Workspaces', 'GET', '/workspaces/{workspaceId}/updates/{updateId}', 'none', 'https://learning.postman.com/api-docs/api-reference/workspaces/get-workspace-update'),
    'workspaces_get_workspace_updates': Operation('Get all workspace updates', 'Workspaces', 'GET', '/workspaces/{workspaceId}/updates', 'none', 'https://learning.postman.com/api-docs/api-reference/workspaces/get-workspace-updates'),
    'workspaces_get_workspaces': Operation('Get all workspaces', 'Workspaces', 'GET', '/workspaces', 'none', 'https://learning.postman.com/api-docs/api-reference/workspaces/get-workspaces'),
    'workspaces_manage_partner_workspace_invites': Operation('Manage Partner Workspace invites', 'Workspaces', 'POST', '/invitations', 'application/json', 'https://learning.postman.com/api-docs/api-reference/workspaces/manage-partner-workspace-invites'),
    'workspaces_patch_workspace_update': Operation('Update a workspace update', 'Workspaces', 'PATCH', '/workspaces/{workspaceId}/updates/{updateId}', 'application/merge-patch+json', 'https://learning.postman.com/api-docs/api-reference/workspaces/patch-workspace-update'),
    'workspaces_transfer_workspace_element': Operation('Transfer element to a workspace', 'Workspaces', 'POST', '/workspaces/{workspaceId}/element-transfers', 'application/json', 'https://learning.postman.com/api-docs/api-reference/workspaces/transfer-workspace-element'),
    'workspaces_transfer_workspace_to_team': Operation('Transfer workspace to a team', 'Workspaces', 'PATCH', '/workspaces/{workspaceId}/transfers', 'application/json', 'https://learning.postman.com/api-docs/api-reference/workspaces/transfer-workspace-to-team'),
    'workspaces_update_workspace': Operation('Update a workspace', 'Workspaces', 'PUT', '/workspaces/{workspaceId}', 'application/json', 'https://learning.postman.com/api-docs/api-reference/workspaces/update-workspace'),
    'workspaces_update_workspace_global_variables': Operation('Update global variables', 'Workspaces', 'PUT', '/workspaces/{workspaceId}/global-variables', 'application/json', 'https://learning.postman.com/api-docs/api-reference/workspaces/update-workspace-global-variables'),
    'workspaces_update_workspace_roles': Operation('Update workspace roles', 'Workspaces', 'PATCH', '/workspaces/{workspaceId}/roles', 'application/json-patch+json', 'https://learning.postman.com/api-docs/api-reference/workspaces/update-workspace-roles'),
}



_API_HOSTS = {
    "global": "https://api.postman.com",
    "eu": "https://api.eu.postman.com",
}
_MAX_RESPONSE_BYTES = 20 * 1024 * 1024


class PostmanApiKeyCredential(BaseModel):
    credential_type: Literal["postman_api_key"] = Field(
        "postman_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., min_length=1, title="Postman API Key", json_schema_extra={"ui:widget": "password"}
    )
    region: Literal["global", "eu"] = Field(
        "global",
        title="API Region",
        description="Select EU only for a Postman Enterprise account hosted in the EU.",
    )

    model_config = ConfigDict(title="Postman API Key", json_schema_extra={
        "x-credential-url": "https://web.postman.co/settings/me/api-keys",
        "x-credential-instructions": "Generate an API key in Postman Account Settings → API keys.",
    })


def _path_title(name: str) -> str:
    title = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name.replace("-", " ")).title()
    return title.replace(" Id", " ID").replace("Api", "API")


def _make_config(name: str, op: Operation) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for parameter in re.findall(r"\{([^}]+)\}", op.path):
        fields[parameter] = (str, Field(..., title=_path_title(parameter)))
    fields["query_json"] = (
        Optional[str],
        Field(
            None,
            title="Query Parameters JSON",
            description="Optional Postman API query parameters as a JSON object. See the operation reference for supported keys.",
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
        ),
    )
    if op.body_type != "none":
        fields["body_json"] = (
            Optional[str],
            Field(
                None,
                title="Request Body JSON",
                description=f"JSON request body for {op.label}. See the operation reference for its fields.",
                json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
            ),
        )
    return create_model(
        "Postman" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(
            Literal[name],
            Field(
                name,
                title=op.label,
                description=f"{op.method} {op.path}. Reference: {op.docs_url}",
                json_schema_extra={
                    "const": name,
                    "ui:hidden": True,
                    "x-category": op.category,
                    "x-is-trigger": False,
                    "x-display-name": op.label,
                },
            ),
        ),
        **fields,
    )


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
class PostmanOnNewMockCallConfig(PollTriggerConfigBase):
    operation: Literal["on_new_mock_call"] = Field("on_new_mock_call", title="On New Mock Call", json_schema_extra={
        "const": "on_new_mock_call", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On New Mock Call",
    })
    mock_id: str = Field(..., min_length=1, title="Mock Server ID",
                         description="Watch requests received by this Postman mock server.")


class PostmanOnNewCollectionForkConfig(PollTriggerConfigBase):
    operation: Literal["on_new_collection_fork"] = Field("on_new_collection_fork", title="On New Collection Fork", json_schema_extra={
        "const": "on_new_collection_fork", "ui:hidden": True, "x-category": "Triggers",
        "x-is-trigger": True, "x-display-name": "On New Collection Fork",
    })
    collection_id: str = Field(..., min_length=1, title="Collection ID",
                               description="Watch new forks of this Postman collection.")


PostmanConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (
    PostmanOnNewMockCallConfig, PostmanOnNewCollectionForkConfig,
)], Discriminator("operation")]


class PostmanNodeConfig(NodeConfig[PostmanConfig, PostmanApiKeyCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


class PostmanNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-postman"
    connection_evidence = ConnectionEvidence(operation="get_authenticated_user", noun="user")
    edit_examples = [
        "List my Postman workspaces",
        "Create a Postman collection",
        "Get a collection",
        "List monitors",
        "List API specifications",
    ]

    @classmethod
    def get_config_model(cls):
        return PostmanNodeConfig

    @classmethod
    def should_propagate_output(cls, output: dict[str, Any], config: dict[str, Any]) -> bool:
        if config.get("operation") in {"on_new_mock_call", "on_new_collection_fork"}:
            return bool(output.get("new_item_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output: dict[str, Any]) -> Optional[dict[str, Any]]:
        operation = output.get("operation")
        if operation not in {"on_new_mock_call", "on_new_collection_fork"}:
            return super().resolve_agent_event(output)
        items = output.get("items", [])
        if not items:
            return None
        lines = []
        for item in items[:10]:
            if operation == "on_new_mock_call":
                request, response = item.get("request") or {}, item.get("response") or {}
                lines.append(f"- {request.get('method', 'Request')} {request.get('path', '')} "
                             f"→ {response.get('statusCode', 'unknown status')} at {item.get('servedAt', '')}; "
                             f"{item.get('responseName', '')} (call id {item.get('id')})")
            else:
                lines.append(f"- {item.get('createdBy', 'Someone')} forked {item.get('forkName', 'a collection')} "
                             f"at {item.get('createdAt', '')} (fork id {item.get('forkId')})")
        if len(items) > 10:
            lines.append(f"- … and {len(items) - 10} more")
        resource = "mock server" if operation == "on_new_mock_call" else "collection"
        return {"text": f"Postman: {len(items)} new {'call(s)' if resource == 'mock server' else 'fork(s)'} "
                        f"for {resource} {output.get('resource_id')}:\n" + "\n".join(lines),
                "conversation_key": None}

    async def _poll_items(self, config, credentials: PostmanApiKeyCredential) -> dict[str, Any]:
        if isinstance(config, PostmanOnNewMockCallConfig):
            name, field, id_field = "mocks_get_mock_call_logs", "call-logs", "id"
            resource_id = config.mock_id
            path = f"/mocks/{quote(resource_id, safe='')}/call-logs"
            params = {"limit": 100, "sort": "servedAt", "direction": "desc"}
        else:
            name, field, id_field = "collections_get_collection_forks", "data", "forkId"
            resource_id = config.collection_id
            path = f"/collections/{quote(resource_id, safe='')}/forks"
            params = {"limit": 100, "direction": "desc"}
        items: list[dict[str, Any]] = []
        cursors: set[str] = set()
        for _ in range(100):
            data = await self._request(OPERATIONS[name], path, credentials, params.copy(), None)
            if not isinstance(data, dict) or not isinstance(data.get(field), list):
                raise ValueError("Postman returned an invalid trigger list response")
            page = data[field]
            if any(not isinstance(item, dict) or not item.get(id_field) for item in page):
                raise ValueError("Postman trigger item is missing its identifier")
            items.extend(page)
            if len(items) > 10000:
                raise ValueError("Postman trigger exceeded 10,000 items; choose a smaller resource")
            cursor = (data.get("meta") or {}).get("nextCursor")
            if not cursor:
                break
            if cursor in cursors:
                raise ValueError("Postman repeated a pagination cursor")
            cursors.add(cursor)
            params["cursor"] = cursor
        else:
            raise ValueError("Postman trigger exceeded 100 pages; choose a smaller resource")
        fresh = await self._filter_unseen(items, lambda item: str(item[id_field]))
        return {"status": "success", "operation": config.operation, "resource_id": resource_id,
                "items": fresh, "new_item_count": len(fresh)}

    @staticmethod
    def _parse_object(raw: Optional[str], label: str) -> dict[str, Any]:
        if raw is None or not raw.strip():
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be a JSON object")
        return value

    @staticmethod
    def _parse_body(raw: Optional[str]) -> Any:
        if raw is None or not raw.strip():
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Request Body JSON must be valid JSON") from exc

    @staticmethod
    def _query_value(value: Any) -> Any:
        if isinstance(value, list):
            return [PostmanNode._query_value(item) for item in value]
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, dict):
            return json.dumps(value, separators=(",", ":"))
        return value

    @staticmethod
    def _safe_error(response: httpx.Response, api_key: str) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("message") or payload.get("error") or payload.get("detail")
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("name")
        else:
            detail = None
        message = str(detail or "request failed")
        return message.replace(api_key, "[redacted]")[:500]

    @staticmethod
    async def _request(
        op: Operation,
        path: str,
        credentials: PostmanApiKeyCredential,
        params: dict[str, Any],
        body: Any,
    ) -> Any:
        headers = {"x-api-key": credentials.api_key, "Accept": op.accept}
        if body is not None:
            headers["Content-Type"] = op.body_type
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.request(
                    op.method,
                    _API_HOSTS[credentials.region] + path,
                    headers=headers,
                    params=params or None,
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise ValueError("Postman API request failed") from exc
        if response.is_error:
            raise ValueError(
                f"Postman API error {response.status_code}: "
                f"{PostmanNode._safe_error(response, credentials.api_key)}"
            )
        if not response.content:
            return {"ok": True}
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise ValueError("Postman response exceeds the 20 MB workflow limit")
        content_type = response.headers.get("content-type", "")
        if "json" in content_type or response.content[:1] in (b"{", b"["):
            try:
                return response.json()
            except ValueError as exc:
                raise ValueError("Postman returned invalid JSON") from exc
        return BinaryOutput(
            data=response.content,
            content_type=content_type or "application/octet-stream",
            filename="postman-response",
        )

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, PostmanNodeConfig):
            raise ValueError("Postman configuration required")
        credentials = self.config.credentials
        if credentials is None:
            raise ValueError("Connect a Postman API key")
        config = self.config.config
        if isinstance(config, (PostmanOnNewMockCallConfig, PostmanOnNewCollectionForkConfig)):
            return await self._poll_items(config, credentials)
        op = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = op.path
        for parameter in re.findall(r"\{([^}]+)\}", path):
            value = values.pop(parameter)
            path = path.replace("{" + parameter + "}", quote(str(value), safe=""))
        params = {
            key: self._query_value(value)
            for key, value in self._parse_object(
                values.pop("query_json", None), "Query Parameters JSON"
            ).items()
        }
        body = self._parse_body(values.pop("body_json", None)) if op.body_type != "none" else None
        data = await self._request(op, path, credentials, params, body)
        return {"status": "success", "operation": config.operation, "data": data}
