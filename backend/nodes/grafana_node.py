"""Grafana HTTP API workflow node.

The curated route catalog is taken from Grafana's published HTTP API.  A
service-account token works on Grafana Cloud and recent self-hosted Grafana;
there is no Grafana OAuth application flow for these API operations.
"""

import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import allow_private_hosts, guarded_async_client, normalize_https_origin

# Curated from Grafana's published HTTP API at https://play.grafana.org/public/api-merged.json.
# Keeping the provider's route catalog here makes this integration self-contained.
OPERATIONS: list[dict[str, Any]] = [{'name': 'list_annotations',
  'category': 'Annotations',
  'method': 'GET',
  'path': '/annotations',
  'title': 'List Annotations',
  'description': 'Find Annotations.',
  'body_required': False,
  'parameters': [{'name': 'from',
                  'field': 'from',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Find annotations created after specific epoch datetime in '
                                 'milliseconds.'},
                 {'name': 'to',
                  'field': 'to',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Find annotations created before specific epoch datetime in '
                                 'milliseconds.'},
                 {'name': 'userId',
                  'field': 'user_id',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Limit response to annotations created by specific user.'},
                 {'name': 'userUID',
                  'field': 'user_uid',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'Limit response to annotations created by a specific user, identified '
                                 'by UID.'},
                 {'name': 'alertId',
                  'field': 'alert_id',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Find annotations for a specified alert rule by its ID.\n'
                                 'deprecated: AlertID is deprecated and will be removed in future '
                                 'versions. Please use AlertUID instead.'},
                 {'name': 'alertUID',
                  'field': 'alert_uid',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'Find annotations for a specified alert rule by its UID.'},
                 {'name': 'dashboardId',
                  'field': 'dashboard_id',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Find annotations that are scoped to a specific dashboard'},
                 {'name': 'dashboardUID',
                  'field': 'dashboard_uid',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'Find annotations that are scoped to a specific dashboard'},
                 {'name': 'panelId',
                  'field': 'panel_id',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Find annotations that are scoped to a specific panel'},
                 {'name': 'limit',
                  'field': 'limit',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Max limit for results returned.'},
                 {'name': 'tags',
                  'field': 'tags',
                  'location': 'query',
                  'type': 'array',
                  'required': False,
                  'description': 'Use this to filter organization annotations. Organization annotations '
                                 'are annotations from an annotation data source that are not connected '
                                 'specifically to a dashboard or panel. You can filter by multiple '
                                 'tags.'},
                 {'name': 'type',
                  'field': 'type',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'Return alerts or user created annotations\n'
                                 'Description:\n'
                                 '- `alert`\n'
                                 '- `annotation`'},
                 {'name': 'matchAny',
                  'field': 'match_any',
                  'location': 'query',
                  'type': 'boolean',
                  'required': False,
                  'description': 'Match any or all tags'}]},
 {'name': 'create_annotation',
  'category': 'Annotations',
  'method': 'POST',
  'path': '/annotations',
  'title': 'Create Annotation',
  'description': 'Create Annotation.',
  'body_required': True,
  'parameters': []},
 {'name': 'get_annotation',
  'category': 'Annotations',
  'method': 'GET',
  'path': '/annotations/{annotation_id}',
  'title': 'Get Annotation',
  'description': 'Get Annotation by ID.',
  'body_required': False,
  'parameters': [{'name': 'annotation_id',
                  'field': 'annotation_id',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'update_annotation',
  'category': 'Annotations',
  'method': 'PUT',
  'path': '/annotations/{annotation_id}',
  'title': 'Update Annotation',
  'description': 'Update Annotation.',
  'body_required': True,
  'parameters': [{'name': 'annotation_id',
                  'field': 'annotation_id',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'delete_annotation',
  'category': 'Annotations',
  'method': 'DELETE',
  'path': '/annotations/{annotation_id}',
  'title': 'Delete Annotation',
  'description': 'Delete Annotation By ID.',
  'body_required': False,
  'parameters': [{'name': 'annotation_id',
                  'field': 'annotation_id',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'patch_annotation',
  'category': 'Annotations',
  'method': 'PATCH',
  'path': '/annotations/{annotation_id}',
  'title': 'Patch Annotation',
  'description': 'Patch Annotation.',
  'body_required': True,
  'parameters': [{'name': 'annotation_id',
                  'field': 'annotation_id',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'save_dashboard',
  'category': 'Dashboards',
  'method': 'POST',
  'path': '/dashboards/db',
  'title': 'Save Dashboard',
  'description': 'Create / Update dashboard',
  'body_required': True,
  'parameters': []},
 {'name': 'get_dashboard',
  'category': 'Dashboards',
  'method': 'GET',
  'path': '/dashboards/uid/{uid}',
  'title': 'Get Dashboard',
  'description': 'Get dashboard by uid.',
  'body_required': False,
  'parameters': [{'name': 'uid',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'delete_dashboard',
  'category': 'Dashboards',
  'method': 'DELETE',
  'path': '/dashboards/uid/{uid}',
  'title': 'Delete Dashboard',
  'description': 'Delete dashboard by uid.',
  'body_required': False,
  'parameters': [{'name': 'uid',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'list_dashboard_versions',
  'category': 'Dashboards',
  'method': 'GET',
  'path': '/dashboards/uid/{uid}/versions',
  'title': 'List Dashboard Versions',
  'description': 'Gets all existing versions for the dashboard using UID.',
  'body_required': False,
  'parameters': [{'name': 'uid',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''},
                 {'name': 'limit',
                  'field': 'limit',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Maximum number of results to return'},
                 {'name': 'start',
                  'field': 'start',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Version to start from when returning queries'}]},
 {'name': 'list_data_sources',
  'category': 'Data Sources',
  'method': 'GET',
  'path': '/datasources',
  'title': 'List Data Sources',
  'description': 'Get all data sources.',
  'body_required': False,
  'parameters': []},
 {'name': 'create_data_source',
  'category': 'Data Sources',
  'method': 'POST',
  'path': '/datasources',
  'title': 'Create Data Source',
  'description': 'Create a data source.',
  'body_required': True,
  'parameters': []},
 {'name': 'get_data_source',
  'category': 'Data Sources',
  'method': 'GET',
  'path': '/datasources/uid/{uid}',
  'title': 'Get Data Source',
  'description': 'Get a single data source by UID.',
  'body_required': False,
  'parameters': [{'name': 'uid',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'update_data_source',
  'category': 'Data Sources',
  'method': 'PUT',
  'path': '/datasources/uid/{uid}',
  'title': 'Update Data Source',
  'description': 'Update an existing data source.',
  'body_required': True,
  'parameters': [{'name': 'uid',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'delete_data_source',
  'category': 'Data Sources',
  'method': 'DELETE',
  'path': '/datasources/uid/{uid}',
  'title': 'Delete Data Source',
  'description': 'Delete an existing data source by UID.',
  'body_required': False,
  'parameters': [{'name': 'uid',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'check_data_source_health',
  'category': 'Data Sources',
  'method': 'GET',
  'path': '/datasources/uid/{uid}/health',
  'title': 'Check Data Source Health',
  'description': 'Sends a health check request to the plugin datasource identified by the UID.',
  'body_required': False,
  'parameters': [{'name': 'uid',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'list_folders',
  'category': 'Folders',
  'method': 'GET',
  'path': '/folders',
  'title': 'List Folders',
  'description': 'Get all folders.',
  'body_required': False,
  'parameters': [{'name': 'limit',
                  'field': 'limit',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Limit the maximum number of folders to return'},
                 {'name': 'page',
                  'field': 'page',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Page index for starting fetching folders'},
                 {'name': 'parentUid',
                  'field': 'parent_uid',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'The parent folder UID'},
                 {'name': 'permission',
                  'field': 'permission',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'Set to `Edit` to return folders that the user can edit'}]},
 {'name': 'create_folder',
  'category': 'Folders',
  'method': 'POST',
  'path': '/folders',
  'title': 'Create Folder',
  'description': 'Create folder.',
  'body_required': True,
  'parameters': []},
 {'name': 'get_folder',
  'category': 'Folders',
  'method': 'GET',
  'path': '/folders/{folder_uid}',
  'title': 'Get Folder',
  'description': 'Get folder by uid.',
  'body_required': False,
  'parameters': [{'name': 'folder_uid',
                  'field': 'folder_uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'update_folder',
  'category': 'Folders',
  'method': 'PUT',
  'path': '/folders/{folder_uid}',
  'title': 'Update Folder',
  'description': 'Update folder. Include its current version in the request body.',
  'body_required': True,
  'parameters': [{'name': 'folder_uid',
                  'field': 'folder_uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'delete_folder',
  'category': 'Folders',
  'method': 'DELETE',
  'path': '/folders/{folder_uid}',
  'title': 'Delete Folder',
  'description': 'Delete folder.',
  'body_required': False,
  'parameters': [{'name': 'folder_uid',
                  'field': 'folder_uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''},
                 {'name': 'forceDeleteRules',
                  'field': 'force_delete_rules',
                  'location': 'query',
                  'type': 'boolean',
                  'required': False,
                  'description': 'If `true` any Grafana 8 Alerts under this folder will be deleted.\n'
                                 'Set to `false` so that the request will fail if the folder contains '
                                 'any Grafana 8 Alerts.'}]},
 {'name': 'get_folder_counts',
  'category': 'Folders',
  'method': 'GET',
  'path': '/folders/{folder_uid}/counts',
  'title': 'Get Folder Counts',
  'description': 'Gets the count of each descendant of a folder by kind. The folder is identified by '
                 'UID.',
  'body_required': False,
  'parameters': [{'name': 'folder_uid',
                  'field': 'folder_uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'move_folder',
  'category': 'Folders',
  'method': 'POST',
  'path': '/folders/{folder_uid}/move',
  'title': 'Move Folder',
  'description': 'Move folder.',
  'body_required': True,
  'parameters': [{'name': 'folder_uid',
                  'field': 'folder_uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'list_library_elements',
  'category': 'Library Elements',
  'method': 'GET',
  'path': '/library-elements',
  'title': 'List Library Elements',
  'description': 'Get all library elements.',
  'body_required': False,
  'parameters': [{'name': 'searchString',
                  'field': 'search_string',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'Part of the name or description searched for.'},
                 {'name': 'kind',
                  'field': 'kind',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Kind of element to search for.\nDescription:\n- 1 - library panels'},
                 {'name': 'sortDirection',
                  'field': 'sort_direction',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'Sort order of elements.\n'
                                 'Description:\n'
                                 '- alpha-asc: ascending\n'
                                 '- alpha-desc: descending'},
                 {'name': 'typeFilter',
                  'field': 'type_filter',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'A comma separated list of types to filter the elements by'},
                 {'name': 'excludeUid',
                  'field': 'exclude_uid',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'Element UID to exclude from search results.'},
                 {'name': 'folderFilter',
                  'field': 'folder_filter',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'A comma separated list of folder ID(s) to filter the elements by.\n'
                                 'Deprecated: Use FolderFilterUIDs instead.'},
                 {'name': 'folderFilterUIDs',
                  'field': 'folder_filter_uids',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'A comma separated list of folder UID(s) to filter the elements by.'},
                 {'name': 'perPage',
                  'field': 'per_page',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'The number of results per page.'},
                 {'name': 'page',
                  'field': 'page',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'The page for a set of records, given that only perPage records are '
                                 'returned at a time. Numbering starts at 1.'}]},
 {'name': 'create_library_element',
  'category': 'Library Elements',
  'method': 'POST',
  'path': '/library-elements',
  'title': 'Create Library Element',
  'description': 'Create library element.',
  'body_required': True,
  'parameters': []},
 {'name': 'get_library_element_by_name',
  'category': 'Library Elements',
  'method': 'GET',
  'path': '/library-elements/name/{library_element_name}',
  'title': 'Get Library Element By Name',
  'description': 'Get library element by name.',
  'body_required': False,
  'parameters': [{'name': 'library_element_name',
                  'field': 'library_element_name',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'get_library_element',
  'category': 'Library Elements',
  'method': 'GET',
  'path': '/library-elements/{library_element_uid}',
  'title': 'Get Library Element',
  'description': 'Get library element by UID.',
  'body_required': False,
  'parameters': [{'name': 'library_element_uid',
                  'field': 'library_element_uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'delete_library_element',
  'category': 'Library Elements',
  'method': 'DELETE',
  'path': '/library-elements/{library_element_uid}',
  'title': 'Delete Library Element',
  'description': 'Delete library element.',
  'body_required': False,
  'parameters': [{'name': 'library_element_uid',
                  'field': 'library_element_uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'update_library_element',
  'category': 'Library Elements',
  'method': 'PATCH',
  'path': '/library-elements/{library_element_uid}',
  'title': 'Update Library Element',
  'description': 'Update library element.',
  'body_required': True,
  'parameters': [{'name': 'library_element_uid',
                  'field': 'library_element_uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'get_library_element_connections',
  'category': 'Library Elements',
  'method': 'GET',
  'path': '/library-elements/{library_element_uid}/connections/',
  'title': 'Get Library Element Connections',
  'description': 'Get library element connections.',
  'body_required': False,
  'parameters': [{'name': 'library_element_uid',
                  'field': 'library_element_uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'list_playlists',
  'category': 'Playlists',
  'method': 'GET',
  'path': '/playlists',
  'title': 'List Playlists',
  'description': 'Get playlists.',
  'body_required': False,
  'parameters': [{'name': 'query',
                  'field': 'query',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': ''},
                 {'name': 'limit',
                  'field': 'limit',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': ''}]},
 {'name': 'create_playlist',
  'category': 'Playlists',
  'method': 'POST',
  'path': '/playlists',
  'title': 'Create Playlist',
  'description': 'Create playlist.',
  'body_required': True,
  'parameters': []},
 {'name': 'get_playlist',
  'category': 'Playlists',
  'method': 'GET',
  'path': '/playlists/{uid}',
  'title': 'Get Playlist',
  'description': 'Get playlist.',
  'body_required': False,
  'parameters': [{'name': 'uid',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'update_playlist',
  'category': 'Playlists',
  'method': 'PUT',
  'path': '/playlists/{uid}',
  'title': 'Update Playlist',
  'description': 'Update playlist.',
  'body_required': True,
  'parameters': [{'name': 'uid',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'delete_playlist',
  'category': 'Playlists',
  'method': 'DELETE',
  'path': '/playlists/{uid}',
  'title': 'Delete Playlist',
  'description': 'Delete playlist.',
  'body_required': False,
  'parameters': [{'name': 'uid',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'get_playlist_items',
  'category': 'Playlists',
  'method': 'GET',
  'path': '/playlists/{uid}/items',
  'title': 'Get Playlist Items',
  'description': 'Get playlist items.',
  'body_required': False,
  'parameters': [{'name': 'uid',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'search_dashboards',
  'category': 'Dashboards',
  'method': 'GET',
  'path': '/search',
  'title': 'Search Dashboards',
  'description': 'Search Dashboards',
  'body_required': False,
  'parameters': [{'name': 'query',
                  'field': 'query',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'Search Query'},
                 {'name': 'tag',
                  'field': 'tag',
                  'location': 'query',
                  'type': 'array',
                  'required': False,
                  'description': 'List of tags to search for'},
                 {'name': 'type',
                  'field': 'type',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'Type to search for, dash-folder or dash-db\n'
                                 'Description:\n'
                                 '- `dash-folder` - Search for folder\n'
                                 '- `dash-db` - Seatch for dashboard'},
                 {'name': 'dashboardIds',
                  'field': 'dashboard_ids',
                  'location': 'query',
                  'type': 'array',
                  'required': False,
                  'description': 'List of dashboard id’s to search for\n'
                                 'This is deprecated: users should use the `dashboardUIDs` query '
                                 'parameter instead'},
                 {'name': 'dashboardUIDs',
                  'field': 'dashboard_uids',
                  'location': 'query',
                  'type': 'array',
                  'required': False,
                  'description': 'List of dashboard uid’s to search for'},
                 {'name': 'folderIds',
                  'field': 'folder_ids',
                  'location': 'query',
                  'type': 'array',
                  'required': False,
                  'description': 'List of folder id’s to search in for dashboards\n'
                                 "If it's `0` then it will query for the top level folders\n"
                                 'This is deprecated: users should use the `folderUIDs` query parameter '
                                 'instead\n'
                                 '\n'
                                 'Deprecated: use FolderUIDs instead'},
                 {'name': 'folderUIDs',
                  'field': 'folder_uids',
                  'location': 'query',
                  'type': 'array',
                  'required': False,
                  'description': 'List of folder UID’s to search in for dashboards\n'
                                 "If it's an empty string then it will query for the top level folders"},
                 {'name': 'starred',
                  'field': 'starred',
                  'location': 'query',
                  'type': 'boolean',
                  'required': False,
                  'description': 'Flag indicating if only starred Dashboards should be returned'},
                 {'name': 'limit',
                  'field': 'limit',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Limit the number of returned results (max 5000)'},
                 {'name': 'page',
                  'field': 'page',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Use this parameter to access hits beyond limit. Numbering starts at '
                                 '1. limit param acts as page size. Only available in Grafana v6.2+.'},
                 {'name': 'permission',
                  'field': 'permission',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'Set to `Edit` to return dashboards/folders that the user can edit'},
                 {'name': 'sort',
                  'field': 'sort',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'Sort method; for listing all the possible sort methods use the search '
                                 'sorting endpoint.'},
                 {'name': 'deleted',
                  'field': 'deleted',
                  'location': 'query',
                  'type': 'boolean',
                  'required': False,
                  'description': 'Flag indicating if only soft deleted Dashboards should be returned'}]},
 {'name': 'create_team',
  'category': 'Teams',
  'method': 'POST',
  'path': '/teams',
  'title': 'Create Team',
  'description': 'Add Team.',
  'body_required': True,
  'parameters': []},
 {'name': 'list_teams',
  'category': 'Teams',
  'method': 'GET',
  'path': '/teams/search',
  'title': 'List Teams',
  'description': 'Team Search With Paging.',
  'body_required': False,
  'parameters': [{'name': 'page',
                  'field': 'page',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': ''},
                 {'name': 'perpage',
                  'field': 'perpage',
                  'location': 'query',
                  'type': 'integer',
                  'required': False,
                  'description': 'Number of items per page\n'
                                 'The totalCount field in the response can be used for pagination list '
                                 'E.g. if totalCount is equal to 100 teams and the perpage parameter is '
                                 'set to 10 then there are 10 pages of teams.'},
                 {'name': 'name',
                  'field': 'name',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': ''},
                 {'name': 'query',
                  'field': 'query',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'If set it will return results where the query value is contained in '
                                 'the name field. Query values with spaces need to be URL encoded.'},
                 {'name': 'accesscontrol',
                  'field': 'accesscontrol',
                  'location': 'query',
                  'type': 'boolean',
                  'required': False,
                  'description': ''},
                 {'name': 'sort',
                  'field': 'sort',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': ''}]},
 {'name': 'get_team_by_id',
  'category': 'Teams',
  'method': 'GET',
  'path': '/teams/{team_id}',
  'title': 'Get Team By ID',
  'description': 'Get Team By ID.',
  'body_required': False,
  'parameters': [{'name': 'team_id',
                  'field': 'team_id',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''},
                 {'name': 'accesscontrol',
                  'field': 'accesscontrol',
                  'location': 'query',
                  'type': 'boolean',
                  'required': False,
                  'description': ''}]},
 {'name': 'update_team',
  'category': 'Teams',
  'method': 'PUT',
  'path': '/teams/{team_id}',
  'title': 'Update Team',
  'description': 'Update Team.',
  'body_required': True,
  'parameters': [{'name': 'team_id',
                  'field': 'team_id',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'delete_team_by_id',
  'category': 'Teams',
  'method': 'DELETE',
  'path': '/teams/{team_id}',
  'title': 'Delete Team By ID',
  'description': 'Delete Team By ID.',
  'body_required': False,
  'parameters': [{'name': 'team_id',
                  'field': 'team_id',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'get_team_members',
  'category': 'Teams',
  'method': 'GET',
  'path': '/teams/{team_id}/members',
  'title': 'Get Team Members',
  'description': 'Get Team Members.',
  'body_required': False,
  'parameters': [{'name': 'team_id',
                  'field': 'team_id',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'set_team_memberships',
  'category': 'Teams',
  'method': 'PUT',
  'path': '/teams/{team_id}/members',
  'title': 'Set Team Memberships',
  'description': 'Set team memberships.',
  'body_required': True,
  'parameters': [{'name': 'team_id',
                  'field': 'team_id',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'add_team_member',
  'category': 'Teams',
  'method': 'POST',
  'path': '/teams/{team_id}/members',
  'title': 'Add Team Member',
  'description': 'Add Team Member.',
  'body_required': True,
  'parameters': [{'name': 'team_id',
                  'field': 'team_id',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': ''}]},
 {'name': 'list_alert_rules',
  'category': 'Alerting',
  'method': 'GET',
  'path': '/v1/provisioning/alert-rules',
  'title': 'List Alert Rules',
  'description': 'Get all the alert rules.',
  'body_required': False,
  'parameters': []},
 {'name': 'create_alert_rule',
  'category': 'Alerting',
  'method': 'POST',
  'path': '/v1/provisioning/alert-rules',
  'title': 'Create Alert Rule',
  'description': 'Create a new alert rule.',
  'body_required': True,
  'parameters': []},
 {'name': 'get_alert_rule',
  'category': 'Alerting',
  'method': 'GET',
  'path': '/v1/provisioning/alert-rules/{UID}',
  'title': 'Get Alert Rule',
  'description': 'Get a specific alert rule by UID.',
  'body_required': False,
  'parameters': [{'name': 'UID',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': 'Alert rule UID'}]},
 {'name': 'update_alert_rule',
  'category': 'Alerting',
  'method': 'PUT',
  'path': '/v1/provisioning/alert-rules/{UID}',
  'title': 'Update Alert Rule',
  'description': 'Update an existing alert rule.',
  'body_required': True,
  'parameters': [{'name': 'UID',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': 'Alert rule UID'}]},
 {'name': 'list_contact_points',
  'category': 'Alerting',
  'method': 'GET',
  'path': '/v1/provisioning/contact-points',
  'title': 'List Contact Points',
  'description': 'Get all the contact points.',
  'body_required': False,
  'parameters': [{'name': 'name',
                  'field': 'name',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'Filter by name'}]},
 {'name': 'create_contact_point',
  'category': 'Alerting',
  'method': 'POST',
  'path': '/v1/provisioning/contact-points',
  'title': 'Create Contact Point',
  'description': 'Create a contact point.',
  'body_required': True,
  'parameters': []},
 {'name': 'update_contact_point',
  'category': 'Alerting',
  'method': 'PUT',
  'path': '/v1/provisioning/contact-points/{UID}',
  'title': 'Update Contact Point',
  'description': 'Update an existing contact point.',
  'body_required': True,
  'parameters': [{'name': 'UID',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': 'UID is the contact point unique identifier'}]},
 {'name': 'delete_contact_point',
  'category': 'Alerting',
  'method': 'DELETE',
  'path': '/v1/provisioning/contact-points/{UID}',
  'title': 'Delete Contact Point',
  'description': 'Delete a contact point.',
  'body_required': False,
  'parameters': [{'name': 'UID',
                  'field': 'uid',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': 'UID is the contact point unique identifier'}]},
 {'name': 'list_mute_timings',
  'category': 'Alerting',
  'method': 'GET',
  'path': '/v1/provisioning/mute-timings',
  'title': 'List Mute Timings',
  'description': 'Get all the mute timings.',
  'body_required': False,
  'parameters': []},
 {'name': 'create_mute_timing',
  'category': 'Alerting',
  'method': 'POST',
  'path': '/v1/provisioning/mute-timings',
  'title': 'Create Mute Timing',
  'description': 'Create a new mute timing.',
  'body_required': True,
  'parameters': []},
 {'name': 'get_mute_timing',
  'category': 'Alerting',
  'method': 'GET',
  'path': '/v1/provisioning/mute-timings/{name}',
  'title': 'Get Mute Timing',
  'description': 'Get a mute timing.',
  'body_required': False,
  'parameters': [{'name': 'name',
                  'field': 'name',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': 'Mute timing name'}]},
 {'name': 'update_mute_timing',
  'category': 'Alerting',
  'method': 'PUT',
  'path': '/v1/provisioning/mute-timings/{name}',
  'title': 'Update Mute Timing',
  'description': 'Replace an existing mute timing.',
  'body_required': True,
  'parameters': [{'name': 'name',
                  'field': 'name',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': 'Mute timing name'}]},
 {'name': 'delete_mute_timing',
  'category': 'Alerting',
  'method': 'DELETE',
  'path': '/v1/provisioning/mute-timings/{name}',
  'title': 'Delete Mute Timing',
  'description': 'Delete a mute timing.',
  'body_required': False,
  'parameters': [{'name': 'name',
                  'field': 'name',
                  'location': 'path',
                  'type': 'string',
                  'required': True,
                  'description': 'Mute timing name'},
                 {'name': 'version',
                  'field': 'version',
                  'location': 'query',
                  'type': 'string',
                  'required': False,
                  'description': 'Version of mute timing to use for optimistic concurrency. Leave empty '
                                 'to disable validation'}]},
 {'name': 'get_notification_policies',
  'category': 'Alerting',
  'method': 'GET',
  'path': '/v1/provisioning/policies',
  'title': 'Get Notification Policies',
  'description': 'Get the notification policy tree.',
  'body_required': False,
  'parameters': []},
 {'name': 'set_notification_policies',
  'category': 'Alerting',
  'method': 'PUT',
  'path': '/v1/provisioning/policies',
  'title': 'Set Notification Policies',
  'description': 'Sets the notification policy tree.',
  'body_required': True,
  'parameters': []},
 {'name': 'reset_notification_policies',
  'category': 'Alerting',
  'method': 'DELETE',
  'path': '/v1/provisioning/policies',
  'title': 'Reset Notification Policies',
  'description': 'Clears the notification policy tree.',
  'body_required': False,
  'parameters': []},
 {'name': 'list_notification_templates',
  'category': 'Alerting',
  'method': 'GET',
  'path': '/v1/provisioning/templates',
  'title': 'List Notification Templates',
  'description': 'Get all notification template groups.',
  'body_required': False,
  'parameters': []}]


logger = logging.getLogger(__name__)


class GrafanaCredential(BaseModel):
    credential_type: Literal["grafana_service_account_token"] = Field(
        "grafana_service_account_token", json_schema_extra={"ui:hidden": True}
    )
    url: str = Field(
        ...,
        title="Grafana URL",
        description="Exact Grafana instance origin, such as https://example.grafana.net",
    )
    token: str = Field(
        ...,
        title="Service Account Token",
        description="Create a service account token in Administration → Users and access → Service accounts.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        title="Grafana Service Account Token",
        json_schema_extra={"x-credential-url": "https://grafana.com/docs/grafana/latest/administration/service-accounts/"}
    )


# Grafana's own MCP server: agents get its tools through a person's Grafana sign-in.
# Grafana Cloud stacks only.
GrafanaMcpCredential = mcp_credential("grafana", "https://mcp.grafana.com/mcp", app="Grafana")


def _origin(raw: str) -> str:
    """Require an exact HTTPS origin, except loopback HTTP in local development."""
    if allow_private_hosts():
        parts = urlsplit(raw)
        if (
            parts.scheme == "http"
            and parts.hostname in {"localhost", "127.0.0.1", "::1"}
            and not parts.username
            and not parts.password
            and parts.path in ("", "/")
            and not parts.query
            and not parts.fragment
        ):
            return raw.rstrip("/")
    return normalize_https_origin(raw, field_name="Grafana URL")


def _field_for_parameter(parameter: dict[str, Any]):
    required = parameter["location"] == "path" or parameter["required"]
    kind = parameter["type"]
    annotation = int if kind == "integer" else bool if kind == "boolean" else str
    if not required:
        annotation = Optional[annotation]
    description = parameter["description"] or (
        f"Grafana {parameter['location']} parameter: {parameter['name']}"
    )
    if kind == "array":
        description += " (comma-separated values)"
    title = parameter["field"].replace("_", " ").title()
    title = re.sub(r"\bUid\b", "UID", title)
    title = re.sub(r"\bId\b", "ID", title)
    return annotation, Field(
        ... if required else None,
        title=title,
        description=description,
    )


def _build_operation_model(operation: dict[str, Any]) -> type[BaseModel]:
    name = operation["name"]
    fields: dict[str, Any] = {
        "operation": (
            Literal[name],
            Field(
                name,
                title=operation["title"],
                json_schema_extra={
                    "const": name,
                    "ui:hidden": True,
                    "x-category": operation["category"],
                    "x-is-trigger": False,
                    "x-display-name": operation["title"],
                    "x-keywords": [operation["category"], name.replace("_", " ")],
                },
            ),
        )
    }
    for parameter in operation["parameters"]:
        fields[parameter["field"]] = _field_for_parameter(parameter)
    if name == "move_folder":
        fields["parent_uid"] = (
            str,
            Field(
                "",
                title="Parent Folder UID",
                description="UID of the destination folder. Leave empty to move the folder under root.",
            ),
        )
    elif operation["body_required"]:
        fields["body"] = (
            str,
            Field(
                ...,
                title="Request Body",
                description=(
                    "JSON object or array accepted by Grafana for this operation. "
                    "See the Grafana HTTP API documentation for its fields."
                ),
                json_schema_extra={"ui:widget": "textarea"},
            ),
        )
    return create_model(
        "Grafana" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        **fields,
    )


_BY_NAME = {operation["name"]: operation for operation in OPERATIONS}
_MODELS = tuple(_build_operation_model(operation) for operation in OPERATIONS)


class GrafanaOnAlertNotificationConfig(WebhookTriggerConfigBase):
    """Receive Grafana's default grouped alert notification payload."""

    operation: Literal["on_alert_notification"] = Field(
        "on_alert_notification", title="On Alert Notification", json_schema_extra={
            "const": "on_alert_notification", "ui:hidden": True,
            "x-category": "Triggers", "x-is-trigger": True,
            "x-display-name": "On Alert Notification",
        })
    contact_point_name: str = Field(
        "", title="Contact Point Name",
        description=("Leave empty for a unique NoClick contact point. After registration, select "
                     "this contact point in your Grafana alert rules or notification policies. "
                     "Requires permission to create contact points and Grafana webhook HMAC support."))
    notification_status: Literal["all", "firing", "resolved"] = Field(
        "all", title="Notification Status",
        description="Receive all notifications, firing groups, or fully resolved groups.")
    webhook_url: Optional[str] = Field(
        None, title="Webhook URL",
        description="Registered with Grafana automatically. Use Grafana's default JSON payload.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


GrafanaConfig = Annotated[Union[_MODELS + (GrafanaOnAlertNotificationConfig,)], Discriminator("operation")]


class GrafanaNodeConfig(NodeConfig[GrafanaConfig, Union[GrafanaCredential, GrafanaMcpCredential]]):
    """Grafana operation and service-account credential."""


class GrafanaNode(ExternalWebhookTriggerMixin, WorkflowNode):
    """Manage dashboards, folders, data sources, annotations and alerting."""

    integration_type = "automation-grafana"
    credential_provider_labels = {"grafana": "Grafana Account"}

    connection_evidence = ConnectionEvidence(operation="list_folders", noun="folders")
    edit_examples = [
        "Find a Grafana dashboard by name and get its JSON definition",
        "Create a Grafana folder and save a dashboard to it",
        "List data sources and check their health",
        "Create a dashboard annotation for a deployment",
        "List Grafana alert rules and contact points",
    ]

    @classmethod
    def get_config_model(cls):
        return GrafanaNodeConfig

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"contact_point_name": (config or {}).get("contact_point_name", "")}

    @staticmethod
    async def _contact_point_request(credential, method, path, *, body=None):
        parsed = GrafanaCredential.model_validate(credential)
        async with guarded_async_client(timeout=30.0) as client:
            response = await client.request(
                method, f"{_origin(parsed.url)}/api/v1/provisioning/contact-points{path}",
                headers={"Authorization": f"Bearer {parsed.token}", "Accept": "application/json"},
                json=body)
        if method == "DELETE" and response.status_code == 404:
            return
        response.raise_for_status()

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        # Grafana's EmbeddedContactPoint contract allows a caller-supplied UID.
        # Settings keys: grafana/alerting receivers/webhook/v1/config.go;
        # signing: Grafana's webhook-notifier documentation.
        uid = "noclick-" + hashlib.sha256(str(node_id).encode()).hexdigest()[:24]
        secret = secrets.token_hex(32)
        await cls._contact_point_request(credential, "POST", "", body={
            "uid": uid, "name": (config or {}).get("contact_point_name") or f"NoClick {uid}",
            "type": "webhook", "disableResolveMessage": False,
            "settings": {"url": webhook_url, "httpMethod": "POST", "hmacConfig": {
                "secret": secret, "header": "X-Grafana-Alerting-Signature",
                "timestampHeader": "X-Grafana-Alerting-Timestamp",
            }},
        })
        return {"external_webhook_id": uid, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        uid = (config or {}).get("external_webhook_id")
        if not uid:
            return
        if not credential:
            raise ValueError("Connect Grafana to remove its contact point")
        await cls._contact_point_request(credential, "DELETE", "/" + quote(str(uid), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        # https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/integrations/webhook-notifier/#hmac-signature
        secret = (config or {}).get("signing_secret")
        normalized = {key.lower(): value for key, value in headers.items()}
        timestamp = normalized.get("x-grafana-alerting-timestamp", "")
        signature = normalized.get("x-grafana-alerting-signature", "")
        if not secret or not re.fullmatch(r"[0-9]{1,12}", timestamp):
            return False
        if abs(time.time() - int(timestamp)) > 300 or not re.fullmatch(r"[0-9a-f]{64}", signature):
            return False
        expected = hmac.new(str(secret).encode(), timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        if (config or {}).get("operation") != "on_alert_notification":
            return False
        status = payload.get("status")
        wanted = (config or {}).get("notification_status") or "all"
        return (status in {"firing", "resolved"} and isinstance(payload.get("alerts"), list)
                and bool(payload["alerts"]) and (wanted == "all" or wanted == status))

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or not isinstance(output.get("alerts"), list):
            return super().resolve_agent_event(output)
        title = output.get("title") or f"Grafana alerts {output.get('status', '')}"
        lines = [str(title), f"Grafana: {output.get('externalURL', '')} (organization {output.get('orgId', '')})",
                 f"Contact point: {output.get('receiver', '')}; status: {output.get('status', '')}"]
        for alert in output["alerts"]:
            if not isinstance(alert, dict):
                continue
            labels = alert.get("labels") or {}
            annotations = alert.get("annotations") or {}
            lines.append(f"\n{labels.get('alertname', 'Alert')} — {alert.get('status', '')}")
            lines.append("Labels: " + ", ".join(f"{key}={value}" for key, value in labels.items()))
            for key, value in annotations.items():
                lines.append(f"{key}: {value}")
            for key in ("fingerprint", "startsAt", "endsAt", "generatorURL", "silenceURL", "dashboardURL", "panelURL", "values"):
                if alert.get(key):
                    lines.append(f"{key}: {alert[key]}")
        if output.get("message"):
            lines += ["", str(output["message"])]
        if output.get("truncatedAlerts"):
            lines.append(f"Additional alerts omitted by Grafana: {output['truncatedAlerts']}")
        return {"text": "\n".join(lines), "title": str(title),
                "conversation_key": f"{output.get('externalURL', '')}:{output.get('orgId', '')}:{output.get('groupKey', '')}"}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        started = time.monotonic()
        config = self.config
        if not isinstance(config, GrafanaNodeConfig):
            raise ValueError("Valid Grafana configuration is required")
        if isinstance(config.config, GrafanaOnAlertNotificationConfig):
            return self.no_event_output("on_alert_notification")
        credential = config.credentials
        if not credential or not credential.token:
            raise ValueError("A Grafana service account token is required")
        origin = _origin(credential.url)
        op = config.config
        spec = _BY_NAME.get(op.operation)
        if spec is None:
            raise ValueError(f"Unsupported Grafana operation: {op.operation}")

        values = op.model_dump(exclude_none=True)
        path = spec["path"]
        for parameter in spec["parameters"]:
            if parameter["location"] == "path":
                field = parameter["field"]
                if field not in values or not str(values[field]).strip():
                    raise ValueError(f"{field} is required")
                path = path.replace(
                    "{" + parameter["name"] + "}", quote(str(values[field]), safe="")
                )
        if re.search(r"\{[^}]+\}", path):
            raise ValueError("Grafana route has an unfilled path parameter")

        params: list[tuple[str, Any]] = []
        for parameter in spec["parameters"]:
            if parameter["location"] != "query":
                continue
            value = values.get(parameter["field"])
            if value is None or value == "":
                continue
            if parameter["type"] == "array":
                params.extend(
                    (parameter["name"], part.strip())
                    for part in str(value).split(",")
                    if part.strip()
                )
            elif isinstance(value, bool):
                params.append((parameter["name"], "true" if value else "false"))
            else:
                params.append((parameter["name"], value))

        body = None
        if op.operation == "move_folder":
            body = {"parentUid": values["parent_uid"]}
        elif spec["body_required"]:
            try:
                body = json.loads(values["body"])
            except (ValueError, TypeError) as exc:
                raise ValueError("Request Body must be valid JSON") from exc
            if not isinstance(body, (dict, list)):
                raise ValueError("Request Body must be a JSON object or array")

        try:
            async with guarded_async_client(timeout=30.0) as client:
                response = await client.request(
                    spec["method"],
                    f"{origin}/api{path}",
                    headers={
                        "Authorization": f"Bearer {credential.token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    params=params or None,
                    json=body,
                )
        except httpx.TimeoutException:
            return {
                "status": "error",
                "action": op.operation,
                "status_code": 408,
                "error": "Grafana request timed out",
            }
        except httpx.HTTPError as exc:
            logger.warning("Grafana %s request failed: %s", op.operation, type(exc).__name__)
            return {
                "status": "error",
                "action": op.operation,
                "status_code": 502,
                "error": f"Grafana request failed: {type(exc).__name__}",
            }

        elapsed = round((time.monotonic() - started) * 1000, 2)
        try:
            payload = response.json() if response.content else {}
        except ValueError:
            payload = {"text": response.text[:2000]}
        if response.status_code >= 400:
            if isinstance(payload, dict):
                message = payload.get("message") or payload.get("error") or response.reason_phrase
            else:
                message = response.reason_phrase
            return {
                "status": "error",
                "action": op.operation,
                "status_code": response.status_code,
                "error": str(message)[:1000],
                "timing_ms": {"total": elapsed},
            }
        data = {"items": payload, "count": len(payload)} if isinstance(payload, list) else payload
        return {
            "status": "success",
            "action": op.operation,
            "status_code": response.status_code,
            "data": data,
            "timing_ms": {"total": elapsed},
        }
