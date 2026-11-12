"""UptimeRobot v3 workflow node.

The local operation catalog is pinned to UptimeRobot's published v3 OpenAPI
document. It covers monitors, incidents, groups, public
status pages, maintenance, alert contacts, integrations, tags, and account data.
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


OPERATIONS = {'bulk_pause_monitors': {'method': 'POST',
                         'path': '/monitors/bulk/pause',
                         'summary': 'Pause monitors by group and/or tag',
                         'category': 'Bulk Monitors',
                         'parameters': [],
                         'body_mime': 'application/json',
                         'body_required': True,
                         'body_fields': [{'name': 'groupId',
                                          'type': 'number',
                                          'required': False,
                                          'description': 'ID of the monitor group to filter by (0 '
                                                         '= default group / ungrouped monitors). '
                                                         'At least one of groupId or tagId must be '
                                                         'provided.',
                                          'enum': None},
                                         {'name': 'tagId',
                                          'type': 'number',
                                          'required': False,
                                          'description': 'ID of the tag to filter by. At least one '
                                                         'of groupId or tagId must be provided. '
                                                         'When both groupId and tagId are '
                                                         'specified, only monitors matching both '
                                                         'filters are affected.',
                                          'enum': None}]},
 'bulk_start_monitors': {'method': 'POST',
                         'path': '/monitors/bulk/start',
                         'summary': 'Start monitors by group and/or tag',
                         'category': 'Bulk Monitors',
                         'parameters': [],
                         'body_mime': 'application/json',
                         'body_required': True,
                         'body_fields': [{'name': 'groupId',
                                          'type': 'number',
                                          'required': False,
                                          'description': 'ID of the monitor group to filter by (0 '
                                                         '= default group / ungrouped monitors). '
                                                         'At least one of groupId or tagId must be '
                                                         'provided.',
                                          'enum': None},
                                         {'name': 'tagId',
                                          'type': 'number',
                                          'required': False,
                                          'description': 'ID of the tag to filter by. At least one '
                                                         'of groupId or tagId must be provided. '
                                                         'When both groupId and tagId are '
                                                         'specified, only monitors matching both '
                                                         'filters are affected.',
                                          'enum': None}]},
 'bulk_update_monitors': {'method': 'POST',
                          'path': '/monitors/bulk/update',
                          'summary': 'Update monitors by group and/or tag',
                          'category': 'Bulk Monitors',
                          'parameters': [],
                          'body_mime': 'application/json',
                          'body_required': True,
                          'body_fields': [{'name': 'groupId',
                                           'type': 'number',
                                           'required': False,
                                           'description': 'ID of the monitor group to filter by (0 '
                                                          '= default group / ungrouped monitors). '
                                                          'At least one of groupId or tagId must '
                                                          'be provided.',
                                           'enum': None},
                                          {'name': 'tagId',
                                           'type': 'number',
                                           'required': False,
                                           'description': 'ID of the tag to filter by. At least '
                                                          'one of groupId or tagId must be '
                                                          'provided. When both groupId and tagId '
                                                          'are specified, only monitors matching '
                                                          'both filters are affected.',
                                           'enum': None},
                                          {'name': 'interval',
                                           'type': 'number',
                                           'required': False,
                                           'description': 'Monitoring interval in seconds',
                                           'enum': None},
                                          {'name': 'timeout',
                                           'type': 'number',
                                           'required': False,
                                           'description': 'Timeout in seconds',
                                           'enum': None},
                                          {'name': 'gracePeriod',
                                           'type': 'number',
                                           'required': False,
                                           'description': 'Grace period in seconds',
                                           'enum': None},
                                          {'name': 'checkSSLErrors',
                                           'type': 'boolean',
                                           'required': False,
                                           'description': 'Whether to check for SSL errors',
                                           'enum': None},
                                          {'name': 'domainExpirationReminder',
                                           'type': 'boolean',
                                           'required': False,
                                           'description': 'Whether to enable domain expiration '
                                                          'reminder',
                                           'enum': None},
                                          {'name': 'sslExpirationReminder',
                                           'type': 'boolean',
                                           'required': False,
                                           'description': 'Whether to enable SSL expiration '
                                                          'reminder',
                                           'enum': None},
                                          {'name': 'responseTimeThreshold',
                                           'type': 'number',
                                           'required': False,
                                           'description': 'Response time threshold in milliseconds',
                                           'enum': None},
                                          {'name': 'customFields',
                                           'type': 'object',
                                           'required': False,
                                           'description': 'Custom key-value metadata to set on all '
                                                          'monitors in the group. Max 20 keys. '
                                                          'Keys: alphanumeric + underscore + '
                                                          'hyphen, max 64 chars. Values: max 255 '
                                                          'chars. Paid plans only.',
                                           'enum': None}]},
 'list_incidents': {'method': 'GET',
                    'path': '/incidents',
                    'summary': 'List incidents',
                    'category': 'Incidents',
                    'parameters': [{'name': 'cursor',
                                    'in': 'query',
                                    'required': False,
                                    'type': 'string',
                                    'description': 'Cursor to paginate through incidents (incident '
                                                   'ID)'},
                                   {'name': 'monitor_id',
                                    'in': 'query',
                                    'required': False,
                                    'type': 'number',
                                    'description': 'Filter incidents by monitor ID'},
                                   {'name': 'monitor_name',
                                    'in': 'query',
                                    'required': False,
                                    'type': 'string',
                                    'description': 'Filter incidents by monitor name (partial '
                                                   'match)'},
                                   {'name': 'started_after',
                                    'in': 'query',
                                    'required': False,
                                    'type': 'string',
                                    'description': 'Filter incidents started after this date (ISO '
                                                   '8601 format)'},
                                   {'name': 'started_before',
                                    'in': 'query',
                                    'required': False,
                                    'type': 'string',
                                    'description': 'Filter incidents started before this date (ISO '
                                                   '8601 format)'}],
                    'body_mime': '',
                    'body_required': False,
                    'body_fields': []},
 'get_incident': {'method': 'GET',
                  'path': '/incidents/{id}',
                  'summary': 'Get an incident by ID',
                  'category': 'Incidents',
                  'parameters': [{'name': 'id',
                                  'in': 'path',
                                  'required': True,
                                  'type': 'string',
                                  'description': 'The incident ID'}],
                  'body_mime': '',
                  'body_required': False,
                  'body_fields': []},
 'list_incident_comments': {'method': 'GET',
                            'path': '/incidents/{id}/comments',
                            'summary': 'List incident comments',
                            'category': 'Incidents',
                            'parameters': [{'name': 'id',
                                            'in': 'path',
                                            'required': True,
                                            'type': 'string',
                                            'description': 'The incident ID'},
                                           {'name': 'cursor',
                                            'in': 'query',
                                            'required': False,
                                            'type': 'string',
                                            'description': 'Cursor to paginate through comments '
                                                           '(comment ID)'},
                                           {'name': 'limit',
                                            'in': 'query',
                                            'required': False,
                                            'type': 'number',
                                            'description': 'Number of comments to return (1-100, '
                                                           'default 50)'}],
                            'body_mime': '',
                            'body_required': False,
                            'body_fields': []},
 'create_incident_comment': {'method': 'POST',
                             'path': '/incidents/{id}/comments',
                             'summary': 'Create incident comment',
                             'category': 'Incidents',
                             'parameters': [{'name': 'id',
                                             'in': 'path',
                                             'required': True,
                                             'type': 'string',
                                             'description': 'ID of the incident'}],
                             'body_mime': 'application/json',
                             'body_required': True,
                             'body_fields': [{'name': 'content',
                                              'type': 'string',
                                              'required': True,
                                              'description': 'Content of the comment',
                                              'enum': None},
                                             {'name': 'publishOnStatusPage',
                                              'type': 'boolean',
                                              'required': False,
                                              'description': 'Whether the comment is published on '
                                                             'the status page',
                                              'enum': None}]},
 'get_incident_activity_log': {'method': 'GET',
                               'path': '/incidents/{id}/activity-log',
                               'summary': 'Get incident activity log',
                               'category': 'Incidents',
                               'parameters': [{'name': 'id',
                                               'in': 'path',
                                               'required': True,
                                               'type': 'string',
                                               'description': 'ID of the incident'}],
                               'body_mime': '',
                               'body_required': False,
                               'body_fields': []},
 'get_incident_alerts': {'method': 'GET',
                         'path': '/incidents/{id}/alerts',
                         'summary': 'Get incident sent alerts',
                         'category': 'Incidents',
                         'parameters': [{'name': 'id',
                                         'in': 'path',
                                         'required': True,
                                         'type': 'string',
                                         'description': 'ID of the incident'}],
                         'body_mime': '',
                         'body_required': False,
                         'body_fields': []},
 'update_incident_comment': {'method': 'PATCH',
                             'path': '/incidents/{id}/comments/{commentId}',
                             'summary': 'Update an incident comment',
                             'category': 'Incidents',
                             'parameters': [{'name': 'id',
                                             'in': 'path',
                                             'required': True,
                                             'type': 'string',
                                             'description': 'The incident ID'},
                                            {'name': 'commentId',
                                             'in': 'path',
                                             'required': True,
                                             'type': 'number',
                                             'description': 'The comment ID'}],
                             'body_mime': 'application/json',
                             'body_required': True,
                             'body_fields': [{'name': 'content',
                                              'type': 'string',
                                              'required': True,
                                              'description': 'Updated content of the comment',
                                              'enum': None},
                                             {'name': 'publishOnStatusPage',
                                              'type': 'boolean',
                                              'required': False,
                                              'description': 'Whether the comment is published on '
                                                             'the status page',
                                              'enum': None}]},
 'delete_incident_comment': {'method': 'DELETE',
                             'path': '/incidents/{id}/comments/{commentId}',
                             'summary': 'Delete incident comment',
                             'category': 'Incidents',
                             'parameters': [{'name': 'id',
                                             'in': 'path',
                                             'required': True,
                                             'type': 'string',
                                             'description': 'ID of the incident'},
                                            {'name': 'commentId',
                                             'in': 'path',
                                             'required': True,
                                             'type': 'number',
                                             'description': 'ID of the comment'}],
                             'body_mime': '',
                             'body_required': False,
                             'body_fields': []},
 'create_monitor_group': {'method': 'POST',
                          'path': '/monitor-groups',
                          'summary': 'Create a monitor group',
                          'category': 'Monitor Groups',
                          'parameters': [],
                          'body_mime': 'application/json',
                          'body_required': True,
                          'body_fields': [{'name': 'name',
                                           'type': 'string',
                                           'required': True,
                                           'description': 'Name of the monitor group',
                                           'enum': None},
                                          {'name': 'monitorIds',
                                           'type': 'array',
                                           'required': False,
                                           'description': 'List of monitor IDs to be assigned to '
                                                          'this group',
                                           'enum': None},
                                          {'name': 'groupIds',
                                           'type': 'array',
                                           'required': False,
                                           'description': 'List of group IDs whose monitors should '
                                                          'be moved to this new group',
                                           'enum': None}]},
 'list_monitor_groups': {'method': 'GET',
                         'path': '/monitor-groups',
                         'summary': 'List monitor groups',
                         'category': 'Monitor Groups',
                         'parameters': [{'name': 'cursor',
                                         'in': 'query',
                                         'required': False,
                                         'type': 'number',
                                         'description': 'Cursor for pagination (ID of the last '
                                                        'item from previous page)'}],
                         'body_mime': '',
                         'body_required': False,
                         'body_fields': []},
 'get_monitor_group': {'method': 'GET',
                       'path': '/monitor-groups/{id}',
                       'summary': 'Get a monitor group by ID',
                       'category': 'Monitor Groups',
                       'parameters': [{'name': 'id',
                                       'in': 'path',
                                       'required': True,
                                       'type': 'number',
                                       'description': 'The monitor group ID'}],
                       'body_mime': '',
                       'body_required': False,
                       'body_fields': []},
 'update_monitor_group': {'method': 'PATCH',
                          'path': '/monitor-groups/{id}',
                          'summary': 'Update a monitor group',
                          'category': 'Monitor Groups',
                          'parameters': [{'name': 'id',
                                          'in': 'path',
                                          'required': True,
                                          'type': 'number',
                                          'description': 'The monitor group ID'}],
                          'body_mime': 'application/json',
                          'body_required': True,
                          'body_fields': [{'name': 'name',
                                           'type': 'string',
                                           'required': False,
                                           'description': 'Name of the monitor group',
                                           'enum': None}]},
 'delete_monitor_group': {'method': 'DELETE',
                          'path': '/monitor-groups/{id}',
                          'summary': 'Delete a monitor group',
                          'category': 'Monitor Groups',
                          'parameters': [{'name': 'id',
                                          'in': 'path',
                                          'required': True,
                                          'type': 'number',
                                          'description': 'The monitor group ID to delete'},
                                         {'name': 'monitorsNewGroupId',
                                          'in': 'query',
                                          'required': False,
                                          'type': 'number',
                                          'description': 'Optional group ID to move monitors to. '
                                                         'If not provided, monitors will be moved '
                                                         'to default group (ID: 0).'}],
                          'body_mime': '',
                          'body_required': False,
                          'body_fields': []},
 'list_monitors': {'method': 'GET',
                   'path': '/monitors',
                   'summary': 'List monitors',
                   'category': 'Monitors',
                   'parameters': [{'name': 'customField',
                                   'in': 'query',
                                   'required': False,
                                   'type': 'array',
                                   'description': 'Filter monitors by custom field key:value '
                                                  'pairs. Format: customField=key:value. Multiple '
                                                  'filters use AND logic. Split on first colon '
                                                  'only.'},
                                  {'name': 'limit',
                                   'in': 'query',
                                   'required': False,
                                   'type': 'number',
                                   'description': 'Maximum number of monitors to return per page. '
                                                  'Default: 50, Min: 1, Max: 200.'},
                                  {'name': 'groupId',
                                   'in': 'query',
                                   'required': False,
                                   'type': 'number',
                                   'description': 'Filter monitors by monitor group ID.'},
                                  {'name': 'status',
                                   'in': 'query',
                                   'required': False,
                                   'type': 'string',
                                   'description': 'Comma-separated list of status values to filter '
                                                  'monitors. Uses OR logic (matches any specified '
                                                  'status). Case-insensitive. Allowed values: '
                                                  'PAUSED, STARTED, UP, LOOKS_DOWN, DOWN.'},
                                  {'name': 'name',
                                   'in': 'query',
                                   'required': False,
                                   'type': 'string',
                                   'description': 'Filter monitors by name. Case-insensitive '
                                                  'partial match on the monitor friendly name.'},
                                  {'name': 'url',
                                   'in': 'query',
                                   'required': False,
                                   'type': 'string',
                                   'description': 'Filter monitors by URL. Case-insensitive '
                                                  'partial match on the monitor URL.'},
                                  {'name': 'tags',
                                   'in': 'query',
                                   'required': False,
                                   'type': 'string',
                                   'description': 'Comma-separated list of tag names to filter '
                                                  'monitors. Uses OR logic (matches any specified '
                                                  'tag). Case-sensitive.'},
                                  {'name': 'cursor',
                                   'in': 'query',
                                   'required': False,
                                   'type': 'number',
                                   'description': 'Cursor to paginate through monitors'}],
                   'body_mime': '',
                   'body_required': False,
                   'body_fields': []},
 'create_monitor': {'method': 'POST',
                    'path': '/monitors',
                    'summary': 'Create a monitor',
                    'category': 'Monitors',
                    'parameters': [],
                    'body_mime': 'application/json',
                    'body_required': True,
                    'body_fields': [{'name': 'friendlyName',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'Friendly name of the monitor',
                                     'enum': None},
                                    {'name': 'interval',
                                     'type': 'number',
                                     'required': False,
                                     'description': 'Interval of check in seconds',
                                     'enum': None},
                                    {'name': 'assignedAlertContacts',
                                     'type': 'array',
                                     'required': False,
                                     'description': 'Alert contacts to be assigned to the monitor. '
                                                    'Threshold and recurrence are only available '
                                                    'in the paid plans, they are always 0 in the '
                                                    'Free Plan',
                                     'enum': None},
                                    {'name': 'tagNames',
                                     'type': 'array',
                                     'required': False,
                                     'description': 'Tags to be assigned to the monitor',
                                     'enum': None},
                                    {'name': 'maintenanceWindowsIds',
                                     'type': 'array',
                                     'required': False,
                                     'description': 'Maintenance windows to be assigned to the '
                                                    'monitor',
                                     'enum': None},
                                    {'name': 'regionalData',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'Region for monitoring: na (North America), eu '
                                                    '(Europe), as (Asia), oc (Oceania). Note: If '
                                                    'both regionalData and regionData are '
                                                    'provided, regionData takes priority.',
                                     'enum': ['na', 'eu', 'as', 'oc']},
                                    {'name': 'responseTimeThreshold',
                                     'type': 'number',
                                     'required': False,
                                     'description': 'Response time threshold in milliseconds. When '
                                                    'provided, the value is applied to all active '
                                                    'regions as regionData.THRESHOLD. Always '
                                                    'returns 0 — use regionData.THRESHOLD for '
                                                    'per-region control.',
                                     'enum': None},
                                    {'name': 'groupId',
                                     'type': 'number',
                                     'required': False,
                                     'description': 'Monitor group ID to assign the monitor to. '
                                                    'Default is 0 (no group).',
                                     'enum': None},
                                    {'name': 'customFields',
                                     'type': 'object',
                                     'required': False,
                                     'description': 'Custom key-value metadata for the monitor. '
                                                    'Max 20 keys. Keys: alphanumeric + underscore '
                                                    '+ hyphen, max 64 chars. Values: max 255 '
                                                    'chars. Paid plans only.',
                                     'enum': None},
                                    {'name': 'httpMethodType',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'HTTP method to use for the request. For HTTP '
                                                    'and Keyword monitors it defaults to HEAD if '
                                                    'omitted',
                                     'enum': ['HEAD',
                                              'GET',
                                              'POST',
                                              'PUT',
                                              'PATCH',
                                              'DELETE',
                                              'OPTIONS',
                                              'QUERY']},
                                    {'name': 'authType',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'Authentication method to use for the request',
                                     'enum': ['NONE', 'HTTP_BASIC', 'DIGEST', 'BEARER']},
                                    {'name': 'httpUsername',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'Username for HTTP Basic authentication',
                                     'enum': None},
                                    {'name': 'httpPassword',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'Password for HTTP Basic authentication',
                                     'enum': None},
                                    {'name': 'postValueType',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'Type of data payload to be sent in the '
                                                    'request. Affects what data is accepted by '
                                                    '"postValueData" field',
                                     'enum': ['KEY_VALUE', 'RAW_JSON']},
                                    {'name': 'customHttpHeaders',
                                     'type': 'object',
                                     'required': False,
                                     'description': 'Custom HTTP headers to be sent in the '
                                                    'request. Must be sent as JSON object with '
                                                    'key-value pairs',
                                     'enum': None},
                                    {'name': 'successHttpResponseCodes',
                                     'type': 'array',
                                     'required': False,
                                     'description': 'Success HTTP response codes. Can contain '
                                                    'specific codes or ranges like 2xx. Default is '
                                                    '[2xx, 3xx]',
                                     'enum': None},
                                    {'name': 'checkSSLErrors',
                                     'type': 'boolean',
                                     'required': False,
                                     'description': 'Whether to check for SSL and domain '
                                                    'expiration errors',
                                     'enum': None},
                                    {'name': 'sslExpirationReminder',
                                     'type': 'boolean',
                                     'required': False,
                                     'description': 'Whether to send a notification when the SSL '
                                                    'certificate is about to expire',
                                     'enum': None},
                                    {'name': 'domainExpirationReminder',
                                     'type': 'boolean',
                                     'required': False,
                                     'description': 'Whether to send a notification when the '
                                                    'domain is about to expire',
                                     'enum': None},
                                    {'name': 'followRedirections',
                                     'type': 'boolean',
                                     'required': False,
                                     'description': 'Whether to follow redirections',
                                     'enum': None},
                                    {'name': 'type',
                                     'type': 'string',
                                     'required': False,
                                     'description': '',
                                     'enum': ['HTTP']},
                                    {'name': 'url',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'URL of the monitor',
                                     'enum': None},
                                    {'name': 'timeout',
                                     'type': 'number',
                                     'required': False,
                                     'description': 'Timeout of check in seconds',
                                     'enum': None}]},
 'get_aggregate_uptime_stats': {'method': 'GET',
                                'path': '/monitors/uptime-stats',
                                'summary': 'Get aggregated uptime statistics',
                                'category': 'Monitors',
                                'parameters': [{'name': 'logLimit',
                                                'in': 'query',
                                                'required': False,
                                                'type': 'number',
                                                'description': 'Maximum number of log entries to '
                                                               'return (1-500).'},
                                               {'name': 'timeFrame',
                                                'in': 'query',
                                                'required': True,
                                                'type': 'string',
                                                'description': 'Timeframe for statistics. Use '
                                                               'CUSTOM with start/end for custom '
                                                               'range.'},
                                               {'name': 'start',
                                                'in': 'query',
                                                'required': False,
                                                'type': 'number',
                                                'description': 'Start timestamp (Unix seconds). '
                                                               'Required when timeFrame=CUSTOM.'},
                                               {'name': 'end',
                                                'in': 'query',
                                                'required': False,
                                                'type': 'number',
                                                'description': 'End timestamp (Unix seconds). '
                                                               'Required when timeFrame=CUSTOM. '
                                                               'Must be > start.'}],
                                'body_mime': '',
                                'body_required': False,
                                'body_fields': []},
 'get_monitor_uptime_stats': {'method': 'GET',
                              'path': '/monitors/{id}/stats/uptime',
                              'summary': 'Get monitor uptime statistics',
                              'category': 'Monitors',
                              'parameters': [{'name': 'id',
                                              'in': 'path',
                                              'required': True,
                                              'type': 'number',
                                              'description': 'The monitor ID'},
                                             {'name': 'from',
                                              'in': 'query',
                                              'required': False,
                                              'type': 'string',
                                              'description': 'Start date for statistics (ISO 8601 '
                                                             'format). Defaults to 24 hours ago.'},
                                             {'name': 'to',
                                              'in': 'query',
                                              'required': False,
                                              'type': 'string',
                                              'description': 'End date for statistics (ISO 8601 '
                                                             'format). Defaults to now.'}],
                              'body_mime': '',
                              'body_required': False,
                              'body_fields': []},
 'get_monitor_response_time_stats_by_region': {'method': 'GET',
                                               'path': '/monitors/{id}/stats/response-time/all',
                                               'summary': 'Get monitor response time statistics by '
                                                          'region',
                                               'category': 'Monitors',
                                               'parameters': [{'name': 'id',
                                                               'in': 'path',
                                                               'required': True,
                                                               'type': 'number',
                                                               'description': 'The monitor ID'},
                                                              {'name': 'from',
                                                               'in': 'query',
                                                               'required': False,
                                                               'type': 'string',
                                                               'description': 'Start date for '
                                                                              'statistics (ISO '
                                                                              '8601 format). '
                                                                              'Defaults to 24 '
                                                                              'hours ago.'},
                                                              {'name': 'to',
                                                               'in': 'query',
                                                               'required': False,
                                                               'type': 'string',
                                                               'description': 'End date for '
                                                                              'statistics (ISO '
                                                                              '8601 format). '
                                                                              'Defaults to now.'},
                                                              {'name': 'includeTimeSeries',
                                                               'in': 'query',
                                                               'required': False,
                                                               'type': 'boolean',
                                                               'description': 'Whether to include '
                                                                              'time series data '
                                                                              'points in the '
                                                                              'response. Defaults '
                                                                              'to false.'}],
                                               'body_mime': '',
                                               'body_required': False,
                                               'body_fields': []},
 'get_monitor_response_time_stats': {'method': 'GET',
                                     'path': '/monitors/{id}/stats/response-time',
                                     'summary': 'Get monitor response time statistics',
                                     'category': 'Monitors',
                                     'parameters': [{'name': 'id',
                                                     'in': 'path',
                                                     'required': True,
                                                     'type': 'number',
                                                     'description': 'The monitor ID'},
                                                    {'name': 'from',
                                                     'in': 'query',
                                                     'required': False,
                                                     'type': 'string',
                                                     'description': 'Start date for statistics '
                                                                    '(ISO 8601 format). Defaults '
                                                                    'to 24 hours ago.'},
                                                    {'name': 'to',
                                                     'in': 'query',
                                                     'required': False,
                                                     'type': 'string',
                                                     'description': 'End date for statistics (ISO '
                                                                    '8601 format). Defaults to '
                                                                    'now.'},
                                                    {'name': 'includeTimeSeries',
                                                     'in': 'query',
                                                     'required': False,
                                                     'type': 'boolean',
                                                     'description': 'Whether to include time '
                                                                    'series data points in the '
                                                                    'response. Defaults to false.'},
                                                    {'name': 'region',
                                                     'in': 'query',
                                                     'required': False,
                                                     'type': 'string',
                                                     'description': 'Filter by region code (na, '
                                                                    'eu, as, oc). When provided, '
                                                                    'only returns data for the '
                                                                    'specified region.'}],
                                     'body_mime': '',
                                     'body_required': False,
                                     'body_fields': []},
 'get_monitor': {'method': 'GET',
                 'path': '/monitors/{id}',
                 'summary': 'Get a monitor by ID',
                 'category': 'Monitors',
                 'parameters': [{'name': 'id',
                                 'in': 'path',
                                 'required': True,
                                 'type': 'number',
                                 'description': ''}],
                 'body_mime': '',
                 'body_required': False,
                 'body_fields': []},
 'update_monitor': {'method': 'PATCH',
                    'path': '/monitors/{id}',
                    'summary': 'Update a monitor',
                    'category': 'Monitors',
                    'parameters': [{'name': 'id',
                                    'in': 'path',
                                    'required': True,
                                    'type': 'number',
                                    'description': ''}],
                    'body_mime': 'application/json',
                    'body_required': True,
                    'body_fields': [{'name': 'friendlyName',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'Friendly name of the monitor',
                                     'enum': None},
                                    {'name': 'url',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'URL of the monitor. For DNS monitors: DNS '
                                                    'server IP or hostname. Not required for '
                                                    'Heartbeat monitor',
                                     'enum': None},
                                    {'name': 'type',
                                     'type': 'string',
                                     'required': False,
                                     'description': '',
                                     'enum': ['HTTP',
                                              'KEYWORD',
                                              'PING',
                                              'PORT',
                                              'HEARTBEAT',
                                              'DNS',
                                              'API',
                                              'UDP',
                                              'VISUAL_COMPARISON']},
                                    {'name': 'port',
                                     'type': 'number',
                                     'required': False,
                                     'description': 'Required for Port and UDP monitors',
                                     'enum': None},
                                    {'name': 'keywordType',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'Required for Keyword monitor',
                                     'enum': ['ALERT_EXISTS', 'ALERT_NOT_EXISTS']},
                                    {'name': 'keywordCaseType',
                                     'type': 'number',
                                     'required': False,
                                     'description': 'Required for Keyword monitor',
                                     'enum': [0, 1]},
                                    {'name': 'keywordValue',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'Required for Keyword monitor',
                                     'enum': None},
                                    {'name': 'interval',
                                     'type': 'number',
                                     'required': False,
                                     'description': 'Interval of check in seconds. Heartbeat '
                                                    'monitors support at most 2678400 seconds (31 '
                                                    'days).',
                                     'enum': None},
                                    {'name': 'timeout',
                                     'type': 'number',
                                     'required': False,
                                     'description': 'Timeout of check in seconds. Only for Http, '
                                                    'Keyword and Port monitors',
                                     'enum': None},
                                    {'name': 'gracePeriod',
                                     'type': 'number',
                                     'required': False,
                                     'description': 'Grace period of check in seconds. Only for '
                                                    'Heartbeat monitor',
                                     'enum': None},
                                    {'name': 'httpUsername',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'Username for HTTP Basic authentication',
                                     'enum': None},
                                    {'name': 'httpPassword',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'Password for HTTP Basic authentication',
                                     'enum': None},
                                    {'name': 'httpMethodType',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'HTTP method to use for the request. For HTTP '
                                                    'and Keyword monitors it defaults to HEAD if '
                                                    'omitted; API monitors default to GET and do '
                                                    'not allow HEAD',
                                     'enum': ['HEAD',
                                              'GET',
                                              'POST',
                                              'PUT',
                                              'PATCH',
                                              'DELETE',
                                              'OPTIONS',
                                              'QUERY']},
                                    {'name': 'authType',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'Authentication method to use for the request. '
                                                    'Only applicable for HTTP and Keyword monitors',
                                     'enum': ['NONE', 'HTTP_BASIC', 'DIGEST', 'BEARER']},
                                    {'name': 'postValueData',
                                     'type': 'object',
                                     'required': False,
                                     'description': 'Data to be sent in the request. Not '
                                                    'applicable for HTTP method type = HEAD. Can '
                                                    'be JSON string or string',
                                     'enum': None},
                                    {'name': 'postValueType',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'Type of data payload to be sent in the '
                                                    'request. Affects what data is accepted by '
                                                    '"postValueData" field',
                                     'enum': ['KEY_VALUE', 'RAW_JSON']},
                                    {'name': 'assignedAlertContacts',
                                     'type': 'array',
                                     'required': False,
                                     'description': 'Alert contacts to be assigned to the monitor. '
                                                    'Threshold and recurrence are only available '
                                                    'in the paid plans, they are always 0 in the '
                                                    'Free Plan',
                                     'enum': None},
                                    {'name': 'customHttpHeaders',
                                     'type': 'object',
                                     'required': False,
                                     'description': 'Custom HTTP headers to be sent in the '
                                                    'request. Must be sent as JSON object with '
                                                    'key-value pairs',
                                     'enum': None},
                                    {'name': 'successHttpResponseCodes',
                                     'type': 'array',
                                     'required': False,
                                     'description': 'Success HTTP response codes. Can contain '
                                                    'specific codes or ranges like 2xx. Default is '
                                                    '[2xx, 3xx]',
                                     'enum': None},
                                    {'name': 'checkSSLErrors',
                                     'type': 'boolean',
                                     'required': False,
                                     'description': 'Whether to check for SSL and domain '
                                                    'expiration errors',
                                     'enum': None},
                                    {'name': 'tagNames',
                                     'type': 'array',
                                     'required': False,
                                     'description': 'Tags to be assigned to the monitor',
                                     'enum': None},
                                    {'name': 'maintenanceWindowsIds',
                                     'type': 'array',
                                     'required': False,
                                     'description': 'Maintenance windows to be assigned to the '
                                                    'monitor',
                                     'enum': None},
                                    {'name': 'domainExpirationReminder',
                                     'type': 'boolean',
                                     'required': False,
                                     'description': 'Whether to send a notification when the '
                                                    'domain is about to expire',
                                     'enum': None},
                                    {'name': 'sslExpirationReminder',
                                     'type': 'boolean',
                                     'required': False,
                                     'description': 'Whether to send a notification when the SSL '
                                                    'certificate is about to expire',
                                     'enum': None},
                                    {'name': 'followRedirections',
                                     'type': 'boolean',
                                     'required': False,
                                     'description': 'Whether to follow redirections',
                                     'enum': None},
                                    {'name': 'responseTimeThreshold',
                                     'type': 'number',
                                     'required': False,
                                     'description': 'Response time threshold in milliseconds. When '
                                                    'provided, the value is applied to all active '
                                                    'regions as regionData.THRESHOLD. Always '
                                                    'returns 0 — use regionData.THRESHOLD for '
                                                    'per-region control.',
                                     'enum': None},
                                    {'name': 'regionalData',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'Region for monitoring: na (North America), eu '
                                                    '(Europe), as (Asia), oc (Oceania). Note: If '
                                                    'both regionalData and regionData are '
                                                    'provided, regionData takes priority.',
                                     'enum': ['na', 'eu', 'as', 'oc']},
                                    {'name': 'groupId',
                                     'type': 'number',
                                     'required': False,
                                     'description': 'Monitor group ID to assign the monitor to. '
                                                    'Use 0 for the default group.',
                                     'enum': None},
                                    {'name': 'customFields',
                                     'type': 'object',
                                     'required': False,
                                     'description': 'Custom key-value metadata for the monitor. '
                                                    'Max 20 keys. Keys: alphanumeric + underscore '
                                                    '+ hyphen, max 64 chars. Values: max 255 '
                                                    'chars. Paid plans only.',
                                     'enum': None},
                                    {'name': 'config',
                                     'type': 'object',
                                     'required': False,
                                     'description': 'Monitor configuration patch. Top-level '
                                                    'shallow merge with existing config: omit keys '
                                                    'to leave unchanged, set a key to null to '
                                                    'remove it, or send `config: null` to clear '
                                                    'all config.',
                                     'enum': None}]},
 'delete_monitor': {'method': 'DELETE',
                    'path': '/monitors/{id}',
                    'summary': 'Delete a monitor',
                    'category': 'Monitors',
                    'parameters': [{'name': 'id',
                                    'in': 'path',
                                    'required': True,
                                    'type': 'number',
                                    'description': ''}],
                    'body_mime': '',
                    'body_required': False,
                    'body_fields': []},
 'reset_monitor': {'method': 'POST',
                   'path': '/monitors/{id}/reset',
                   'summary': 'Reset stats for a monitor',
                   'category': 'Monitors',
                   'parameters': [{'name': 'id',
                                   'in': 'path',
                                   'required': True,
                                   'type': 'number',
                                   'description': ''}],
                   'body_mime': 'application/json',
                   'body_required': False,
                   'body_fields': []},
 'pause_monitor': {'method': 'POST',
                   'path': '/monitors/{id}/pause',
                   'summary': 'Pause a monitor',
                   'category': 'Monitors',
                   'parameters': [{'name': 'id',
                                   'in': 'path',
                                   'required': True,
                                   'type': 'number',
                                   'description': ''}],
                   'body_mime': 'application/json',
                   'body_required': False,
                   'body_fields': []},
 'start_monitor': {'method': 'POST',
                   'path': '/monitors/{id}/start',
                   'summary': 'Start a monitor',
                   'category': 'Monitors',
                   'parameters': [{'name': 'id',
                                   'in': 'path',
                                   'required': True,
                                   'type': 'number',
                                   'description': ''}],
                   'body_mime': 'application/json',
                   'body_required': False,
                   'body_fields': []},
 'list_status_pages': {'method': 'GET',
                       'path': '/psps',
                       'summary': 'List PSPs',
                       'category': 'Status Pages',
                       'parameters': [{'name': 'cursor',
                                       'in': 'query',
                                       'required': False,
                                       'type': 'number',
                                       'description': 'Cursor to paginate through PSPs'}],
                       'body_mime': '',
                       'body_required': False,
                       'body_fields': []},
 'create_status_page': {'method': 'POST',
                        'path': '/psps',
                        'summary': 'Create a PSP',
                        'category': 'Status Pages',
                        'parameters': [],
                        'body_mime': 'multipart/form-data',
                        'body_required': True,
                        'body_fields': [{'name': 'monitorIds',
                                         'type': 'array',
                                         'required': False,
                                         'description': 'List of monitor IDs to be assigned to the '
                                                        'PSP',
                                         'enum': None},
                                        {'name': 'tagIds',
                                         'type': 'array',
                                         'required': False,
                                         'description': 'List of tag IDs to be assigned to the PSP',
                                         'enum': None},
                                        {'name': 'autoAddMonitors',
                                         'type': 'boolean',
                                         'required': False,
                                         'description': 'If enabled all monitors (old and new) '
                                                        'will be added to PSP automatically. In '
                                                        'this case "monitorIds" property will be '
                                                        'ignored',
                                         'enum': None},
                                        {'name': 'friendlyName',
                                         'type': 'string',
                                         'required': True,
                                         'description': 'Friendly name of the Public Status Page',
                                         'enum': None},
                                        {'name': 'password',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'Password protection for the Public Status '
                                                        'Page',
                                         'enum': None},
                                        {'name': 'customDomain',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'Provide when you want to use custom '
                                                        'domain for the Public Status Page',
                                         'enum': None},
                                        {'name': 'hideUrlLinks',
                                         'type': 'boolean',
                                         'required': False,
                                         'description': 'This will hide "Powered by UptimeRobot" '
                                                        'link in footer',
                                         'enum': None},
                                        {'name': 'noIndex',
                                         'type': 'boolean',
                                         'required': False,
                                         'description': 'Set HTML meta tag to allow or disallow '
                                                        'search engines to index your status page',
                                         'enum': None},
                                        {'name': 'gaCode',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'Available only for a Custom Domain status '
                                                        'page',
                                         'enum': None},
                                        {'name': 'sort',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'Sort monitors by friendly name or their '
                                                        'statuses',
                                         'enum': ['FriendlyNameAsc',
                                                  'FriendlyNameDesc',
                                                  'StatusUpDownPaused',
                                                  'StatusDownUpPaused']},
                                        {'name': 'status',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'Send "ENABLED" to publish the status '
                                                        'page, "PAUSED" to un-publish it',
                                         'enum': ['PAUSED', 'ENABLED']},
                                        {'name': 'subscription',
                                         'type': 'boolean',
                                         'required': False,
                                         'description': 'Subscribers can subscribe to receive '
                                                        'announcements via an e-mail.',
                                         'enum': None},
                                        {'name': 'shareAnalyticsConsent',
                                         'type': 'boolean',
                                         'required': False,
                                         'description': 'Help us improve the Status Pages by '
                                                        'sharing the analytics data with us.',
                                         'enum': None},
                                        {'name': 'homepageLink',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'The link target for the logo (or main '
                                                        'title) on status page. Usually leads to '
                                                        'your homepage.',
                                         'enum': None},
                                        {'name': 'showCookieBar',
                                         'type': 'boolean',
                                         'required': False,
                                         'description': 'Available only for a Custom domain status '
                                                        'page',
                                         'enum': None},
                                        {'name': 'useSmallCookieConsentModal',
                                         'type': 'boolean',
                                         'required': False,
                                         'description': 'Allowing visitor to interact with the '
                                                        'page - should not be used on public pages',
                                         'enum': None}]},
 'get_status_page': {'method': 'GET',
                     'path': '/psps/{id}',
                     'summary': 'Get a PSP by ID',
                     'category': 'Status Pages',
                     'parameters': [{'name': 'id',
                                     'in': 'path',
                                     'required': True,
                                     'type': 'number',
                                     'description': ''}],
                     'body_mime': '',
                     'body_required': False,
                     'body_fields': []},
 'update_status_page': {'method': 'PATCH',
                        'path': '/psps/{id}',
                        'summary': 'Update a PSP',
                        'category': 'Status Pages',
                        'parameters': [{'name': 'id',
                                        'in': 'path',
                                        'required': True,
                                        'type': 'number',
                                        'description': ''}],
                        'body_mime': 'multipart/form-data',
                        'body_required': True,
                        'body_fields': [{'name': 'monitorIds',
                                         'type': 'array',
                                         'required': False,
                                         'description': 'List of monitor IDs to be assigned to the '
                                                        'PSP',
                                         'enum': None},
                                        {'name': 'tagIds',
                                         'type': 'array',
                                         'required': False,
                                         'description': 'List of tag IDs to be assigned to the PSP',
                                         'enum': None},
                                        {'name': 'autoAddMonitors',
                                         'type': 'boolean',
                                         'required': False,
                                         'description': 'If enabled all monitors (old and new) '
                                                        'will be added to PSP automatically. In '
                                                        'this case "monitorIds" property will be '
                                                        'ignored',
                                         'enum': None},
                                        {'name': 'friendlyName',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'Friendly name of the Public Status Page',
                                         'enum': None},
                                        {'name': 'password',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'Password protection for the Public Status '
                                                        'Page',
                                         'enum': None},
                                        {'name': 'customDomain',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'Provide when you want to use custom '
                                                        'domain for the Public Status Page',
                                         'enum': None},
                                        {'name': 'hideUrlLinks',
                                         'type': 'boolean',
                                         'required': False,
                                         'description': 'This will hide "Powered by UptimeRobot" '
                                                        'link in footer',
                                         'enum': None},
                                        {'name': 'noIndex',
                                         'type': 'boolean',
                                         'required': False,
                                         'description': 'Set HTML meta tag to allow or disallow '
                                                        'search engines to index your status page',
                                         'enum': None},
                                        {'name': 'gaCode',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'Available only for a Custom Domain status '
                                                        'page',
                                         'enum': None},
                                        {'name': 'sort',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'Sort monitors by friendly name or their '
                                                        'statuses',
                                         'enum': ['FriendlyNameAsc',
                                                  'FriendlyNameDesc',
                                                  'StatusUpDownPaused',
                                                  'StatusDownUpPaused']},
                                        {'name': 'status',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'Send "ENABLED" to publish the status '
                                                        'page, "PAUSED" to un-publish it',
                                         'enum': ['PAUSED', 'ENABLED']},
                                        {'name': 'subscription',
                                         'type': 'boolean',
                                         'required': False,
                                         'description': 'Subscribers can subscribe to receive '
                                                        'announcements via an e-mail.',
                                         'enum': None},
                                        {'name': 'shareAnalyticsConsent',
                                         'type': 'boolean',
                                         'required': False,
                                         'description': 'Help us improve the Status Pages by '
                                                        'sharing the analytics data with us.',
                                         'enum': None},
                                        {'name': 'homepageLink',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'The link target for the logo (or main '
                                                        'title) on status page. Usually leads to '
                                                        'your homepage.',
                                         'enum': None},
                                        {'name': 'showCookieBar',
                                         'type': 'boolean',
                                         'required': False,
                                         'description': 'Available only for a Custom domain status '
                                                        'page',
                                         'enum': None},
                                        {'name': 'useSmallCookieConsentModal',
                                         'type': 'boolean',
                                         'required': False,
                                         'description': 'Allowing visitor to interact with the '
                                                        'page - should not be used on public pages',
                                         'enum': None},
                                        {'name': 'pinnedAnnouncementId',
                                         'type': 'number',
                                         'required': False,
                                         'description': '',
                                         'enum': None}]},
 'delete_status_page': {'method': 'DELETE',
                        'path': '/psps/{id}',
                        'summary': 'Delete a PSP',
                        'category': 'Status Pages',
                        'parameters': [{'name': 'id',
                                        'in': 'path',
                                        'required': True,
                                        'type': 'number',
                                        'description': ''}],
                        'body_mime': '',
                        'body_required': False,
                        'body_fields': []},
 'list_announcements': {'method': 'GET',
                        'path': '/psps/{pspId}/announcements',
                        'summary': 'List announcements',
                        'category': 'Announcements',
                        'parameters': [{'name': 'pspId',
                                        'in': 'path',
                                        'required': True,
                                        'type': 'number',
                                        'description': 'ID of the Public Status Page'},
                                       {'name': 'status',
                                        'in': 'query',
                                        'required': False,
                                        'type': 'string',
                                        'description': 'Filter announcements by status'},
                                       {'name': 'cursor',
                                        'in': 'query',
                                        'required': False,
                                        'type': 'number',
                                        'description': 'Cursor to paginate through announcements'}],
                        'body_mime': '',
                        'body_required': False,
                        'body_fields': []},
 'create_announcement': {'method': 'POST',
                         'path': '/psps/{pspId}/announcements',
                         'summary': 'Create an announcement',
                         'category': 'Announcements',
                         'parameters': [{'name': 'pspId',
                                         'in': 'path',
                                         'required': True,
                                         'type': 'number',
                                         'description': 'ID of the Public Status Page'}],
                         'body_mime': 'application/json',
                         'body_required': True,
                         'body_fields': [{'name': 'title',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'Title of the announcement',
                                          'enum': None},
                                         {'name': 'content',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'Content of the announcement',
                                          'enum': None},
                                         {'name': 'status',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'Status of the announcement. Possible '
                                                         'values: Offline (draft, not visible on '
                                                         'status page), Pending (scheduled for '
                                                         'publication), Published (currently '
                                                         'visible on status page), Archived '
                                                         '(historical record, no longer visible)',
                                          'enum': ['Offline', 'Pending', 'Published', 'Archived']},
                                         {'name': 'type',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'Type of the announcement. Possible '
                                                         'values: Info (general information), '
                                                         'Maintenance (scheduled maintenance '
                                                         'notification), Issue (incident or issue '
                                                         'notification)',
                                          'enum': ['Info', 'Maintenance', 'Issue']},
                                         {'name': 'startDate',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'Start date of the announcement (ISO 8601 '
                                                         'format)',
                                          'enum': None},
                                         {'name': 'endDate',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'End date of the announcement (ISO 8601 '
                                                         'format)',
                                          'enum': None}]},
 'get_announcement': {'method': 'GET',
                      'path': '/psps/{pspId}/announcements/{id}',
                      'summary': 'Get an announcement by ID',
                      'category': 'Announcements',
                      'parameters': [{'name': 'pspId',
                                      'in': 'path',
                                      'required': True,
                                      'type': 'number',
                                      'description': 'ID of the Public Status Page'},
                                     {'name': 'id',
                                      'in': 'path',
                                      'required': True,
                                      'type': 'number',
                                      'description': 'ID of the announcement'}],
                      'body_mime': '',
                      'body_required': False,
                      'body_fields': []},
 'update_announcement': {'method': 'PATCH',
                         'path': '/psps/{pspId}/announcements/{id}',
                         'summary': 'Update an announcement',
                         'category': 'Announcements',
                         'parameters': [{'name': 'pspId',
                                         'in': 'path',
                                         'required': True,
                                         'type': 'number',
                                         'description': 'ID of the Public Status Page'},
                                        {'name': 'id',
                                         'in': 'path',
                                         'required': True,
                                         'type': 'number',
                                         'description': 'ID of the announcement to update'}],
                         'body_mime': 'application/json',
                         'body_required': True,
                         'body_fields': [{'name': 'title',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'Title of the announcement',
                                          'enum': None},
                                         {'name': 'content',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'Content of the announcement',
                                          'enum': None},
                                         {'name': 'status',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'Status of the announcement. Possible '
                                                         'values: Offline (draft, not visible on '
                                                         'status page), Pending (scheduled for '
                                                         'publication), Published (currently '
                                                         'visible on status page), Archived '
                                                         '(historical record, no longer visible)',
                                          'enum': ['Offline', 'Pending', 'Published', 'Archived']},
                                         {'name': 'type',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'Type of the announcement. Possible '
                                                         'values: Info (general information), '
                                                         'Maintenance (scheduled maintenance '
                                                         'notification), Issue (incident or issue '
                                                         'notification)',
                                          'enum': ['Info', 'Maintenance', 'Issue']},
                                         {'name': 'startDate',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'Start date of the announcement (ISO 8601 '
                                                         'format)',
                                          'enum': None},
                                         {'name': 'endDate',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'End date of the announcement (ISO 8601 '
                                                         'format)',
                                          'enum': None}]},
 'pin_announcement': {'method': 'POST',
                      'path': '/psps/{pspId}/announcements/{id}/pin',
                      'summary': 'Pin an announcement',
                      'category': 'Announcements',
                      'parameters': [{'name': 'pspId',
                                      'in': 'path',
                                      'required': True,
                                      'type': 'number',
                                      'description': 'ID of the Public Status Page'},
                                     {'name': 'id',
                                      'in': 'path',
                                      'required': True,
                                      'type': 'number',
                                      'description': 'ID of the announcement to pin'}],
                      'body_mime': '',
                      'body_required': False,
                      'body_fields': []},
 'unpin_announcement': {'method': 'POST',
                        'path': '/psps/{pspId}/announcements/{id}/unpin',
                        'summary': 'Unpin an announcement',
                        'category': 'Announcements',
                        'parameters': [{'name': 'pspId',
                                        'in': 'path',
                                        'required': True,
                                        'type': 'number',
                                        'description': 'ID of the Public Status Page'},
                                       {'name': 'id',
                                        'in': 'path',
                                        'required': True,
                                        'type': 'number',
                                        'description': 'ID of the announcement to unpin'}],
                        'body_mime': '',
                        'body_required': False,
                        'body_fields': []},
 'list_maintenance_windows': {'method': 'GET',
                              'path': '/maintenance-windows',
                              'summary': 'List maintenance windows',
                              'category': 'Maintenance Windows',
                              'parameters': [{'name': 'cursor',
                                              'in': 'query',
                                              'required': False,
                                              'type': 'string',
                                              'description': ''}],
                              'body_mime': '',
                              'body_required': False,
                              'body_fields': []},
 'create_maintenance_window': {'method': 'POST',
                               'path': '/maintenance-windows',
                               'summary': 'Create a maintenance window',
                               'category': 'Maintenance Windows',
                               'parameters': [],
                               'body_mime': 'application/json',
                               'body_required': True,
                               'body_fields': [{'name': 'name',
                                                'type': 'string',
                                                'required': True,
                                                'description': 'Friendly name of the maintenance '
                                                               'window',
                                                'enum': None},
                                               {'name': 'autoAddMonitors',
                                                'type': 'boolean',
                                                'required': False,
                                                'description': 'If true, all monitors are '
                                                               'automatically added to this '
                                                               'maintenance window',
                                                'enum': None},
                                               {'name': 'interval',
                                                'type': 'string',
                                                'required': True,
                                                'description': '',
                                                'enum': ['once', 'daily', 'weekly', 'monthly']},
                                               {'name': 'date',
                                                'type': 'string',
                                                'required': True,
                                                'description': 'Start date of the maintenance '
                                                               'window in YYYY-MM-DD format (years '
                                                               '19xx or 20xx only)',
                                                'enum': None},
                                               {'name': 'time',
                                                'type': 'string',
                                                'required': True,
                                                'description': 'Start time of the maintenance '
                                                               'window in HH:mm:ss format',
                                                'enum': None},
                                               {'name': 'duration',
                                                'type': 'number',
                                                'required': True,
                                                'description': 'Duration of the maintenance window '
                                                               'in minutes. Maintenance window '
                                                               'will be active for this duration',
                                                'enum': None},
                                               {'name': 'days',
                                                'type': 'array',
                                                'required': False,
                                                'description': '(only needed for weekly and '
                                                               'monthly maintenance windows). E.g. '
                                                               '[2, 4, 5] for Tuesday, Thursday '
                                                               'and Friday or [10, 17, 26] for the '
                                                               'days of the month. -1 for last day '
                                                               'of the month)',
                                                'enum': None},
                                               {'name': 'monitorIds',
                                                'type': 'array',
                                                'required': False,
                                                'description': 'List of monitor IDs to be assigned '
                                                               'to the maintenance window',
                                                'enum': None}]},
 'get_maintenance_window': {'method': 'GET',
                            'path': '/maintenance-windows/{id}',
                            'summary': 'Get a maintenance window by ID',
                            'category': 'Maintenance Windows',
                            'parameters': [{'name': 'id',
                                            'in': 'path',
                                            'required': True,
                                            'type': 'number',
                                            'description': 'ID of the maintenance window'}],
                            'body_mime': '',
                            'body_required': False,
                            'body_fields': []},
 'update_maintenance_window': {'method': 'PATCH',
                               'path': '/maintenance-windows/{id}',
                               'summary': 'Update a maintenance window',
                               'category': 'Maintenance Windows',
                               'parameters': [{'name': 'id',
                                               'in': 'path',
                                               'required': True,
                                               'type': 'number',
                                               'description': 'ID of the maintenance window'}],
                               'body_mime': 'application/json',
                               'body_required': True,
                               'body_fields': [{'name': 'name',
                                                'type': 'string',
                                                'required': False,
                                                'description': 'Name of the maintenance window',
                                                'enum': None},
                                               {'name': 'interval',
                                                'type': 'string',
                                                'required': False,
                                                'description': '',
                                                'enum': ['once', 'daily', 'weekly', 'monthly']},
                                               {'name': 'date',
                                                'type': 'string',
                                                'required': False,
                                                'description': 'Start date of the maintenance '
                                                               'window in YYYY-MM-DD format (years '
                                                               '19xx or 20xx only)',
                                                'enum': None},
                                               {'name': 'time',
                                                'type': 'string',
                                                'required': False,
                                                'description': 'Time format in HH:mm:ss',
                                                'enum': None},
                                               {'name': 'duration',
                                                'type': 'number',
                                                'required': False,
                                                'description': 'Duration in minutes',
                                                'enum': None},
                                               {'name': 'days',
                                                'type': 'array',
                                                'required': False,
                                                'description': '(only needed for weekly and '
                                                               'monthly maintenance windows). E.g. '
                                                               '[2, 4, 5] for Tuesday, Thursday '
                                                               'and Friday or [10, 17, 26] for the '
                                                               'days of the month. -1 for last day '
                                                               'of the month)',
                                                'enum': None},
                                               {'name': 'monitorIds',
                                                'type': 'array',
                                                'required': False,
                                                'description': 'Array of monitor IDs to associate '
                                                               'with this maintenance window',
                                                'enum': None},
                                               {'name': 'status',
                                                'type': 'string',
                                                'required': False,
                                                'description': 'Pause or resume the maintenance '
                                                               'window. `paused` stops it from '
                                                               'suppressing alerts; `active` '
                                                               're-enables it. Omit to leave the '
                                                               'current status unchanged.',
                                                'enum': ['active', 'paused']}]},
 'delete_maintenance_window': {'method': 'DELETE',
                               'path': '/maintenance-windows/{id}',
                               'summary': 'Delete a maintenance window',
                               'category': 'Maintenance Windows',
                               'parameters': [{'name': 'id',
                                               'in': 'path',
                                               'required': True,
                                               'type': 'number',
                                               'description': ''}],
                               'body_mime': '',
                               'body_required': False,
                               'body_fields': []},
 'get_current_user': {'method': 'GET',
                      'path': '/user/me',
                      'summary': 'Get current user',
                      'category': 'Account',
                      'parameters': [],
                      'body_mime': '',
                      'body_required': False,
                      'body_fields': []},
 'get_user_alert_contacts': {'method': 'GET',
                             'path': '/user/alert-contacts',
                             'summary': 'Get alert contacts',
                             'category': 'Account',
                             'parameters': [],
                             'body_mime': '',
                             'body_required': False,
                             'body_fields': []},
 'get_all_alert_contacts': {'method': 'GET',
                            'path': '/user/all-alert-contacts',
                            'summary': 'Get all alert contacts',
                            'category': 'Account',
                            'parameters': [],
                            'body_mime': '',
                            'body_required': False,
                            'body_fields': []},
 'list_integrations': {'method': 'GET',
                       'path': '/integrations',
                       'summary': 'List Integrations',
                       'category': 'Integrations',
                       'parameters': [{'name': 'includeOrgMembers',
                                       'in': 'query',
                                       'required': False,
                                       'type': 'boolean',
                                       'description': 'When true and the caller owns an '
                                                      "organization, include each active member's "
                                                      'personal alert contacts (EmailToSms / Email '
                                                      '/ ProSms / Voice) in the response. Used by '
                                                      'the v2 getAlertContacts proxy to restore '
                                                      'the legacy org-roster scope.'},
                                      {'name': 'cursor',
                                       'in': 'query',
                                       'required': False,
                                       'type': 'number',
                                       'description': 'Cursor to paginate through the '
                                                      'integrations'}],
                       'body_mime': '',
                       'body_required': False,
                       'body_fields': []},
 'create_integration': {'method': 'POST',
                        'path': '/integrations',
                        'summary': 'Create an Integration',
                        'category': 'Integrations',
                        'parameters': [],
                        'body_mime': 'application/json',
                        'body_required': True,
                        'body_fields': []},
 'get_integration': {'method': 'GET',
                     'path': '/integrations/{id}',
                     'summary': 'Get an integration by ID',
                     'category': 'Integrations',
                     'parameters': [{'name': 'id',
                                     'in': 'path',
                                     'required': True,
                                     'type': 'number',
                                     'description': 'ID of the integration'}],
                     'body_mime': '',
                     'body_required': False,
                     'body_fields': []},
 'update_integration': {'method': 'PATCH',
                        'path': '/integrations/{id}',
                        'summary': 'Update an Integration',
                        'category': 'Integrations',
                        'parameters': [{'name': 'id',
                                        'in': 'path',
                                        'required': True,
                                        'type': 'number',
                                        'description': 'ID of the integration'}],
                        'body_mime': 'application/json',
                        'body_required': True,
                        'body_fields': []},
 'delete_integration': {'method': 'DELETE',
                        'path': '/integrations/{id}',
                        'summary': 'Delete an Integration',
                        'category': 'Integrations',
                        'parameters': [{'name': 'id',
                                        'in': 'path',
                                        'required': True,
                                        'type': 'number',
                                        'description': ''}],
                        'body_mime': '',
                        'body_required': False,
                        'body_fields': []},
 'list_alert_contacts': {'method': 'GET',
                         'path': '/alert-contacts',
                         'summary': 'List personal alert contacts',
                         'category': 'Alert Contacts',
                         'parameters': [{'name': 'cursor',
                                         'in': 'query',
                                         'required': False,
                                         'type': 'number',
                                         'description': 'Cursor to paginate through the personal '
                                                        'alert contacts'}],
                         'body_mime': '',
                         'body_required': False,
                         'body_fields': []},
 'create_alert_contact': {'method': 'POST',
                          'path': '/alert-contacts',
                          'summary': 'Create a personal alert contact',
                          'category': 'Alert Contacts',
                          'parameters': [],
                          'body_mime': 'application/json',
                          'body_required': True,
                          'body_fields': [{'name': 'type',
                                           'type': 'string',
                                           'required': True,
                                           'description': 'Personal alert-contact type. Email and '
                                                          'push (MobileAppOld/MobileApp) are '
                                                          'creatable here; Pro SMS and voice '
                                                          'require phone verification.',
                                           'enum': ['Email',
                                                    'ProSms',
                                                    'Voice',
                                                    'MobileAppOld',
                                                    'MobileApp']},
                                          {'name': 'friendlyName',
                                           'type': 'string',
                                           'required': False,
                                           'description': 'Display name of the alert contact',
                                           'enum': None},
                                          {'name': 'enableNotificationsFor',
                                           'type': 'number',
                                           'required': False,
                                           'description': '',
                                           'enum': [0, 1, 2, 3]},
                                          {'name': 'value',
                                           'type': 'string',
                                           'required': False,
                                           'description': 'Email address (required for Email '
                                                          'contacts)',
                                           'enum': None},
                                          {'name': 'deviceName',
                                           'type': 'string',
                                           'required': False,
                                           'description': 'Device name (push)',
                                           'enum': None},
                                          {'name': 'oneSignalSubscriptionId',
                                           'type': 'string',
                                           'required': False,
                                           'description': 'OneSignal subscription ID (push)',
                                           'enum': None},
                                          {'name': 'oneSignalUserId',
                                           'type': 'string',
                                           'required': False,
                                           'description': 'OneSignal user ID (push)',
                                           'enum': None},
                                          {'name': 'deviceFingerprint',
                                           'type': 'string',
                                           'required': False,
                                           'description': 'Device fingerprint (push)',
                                           'enum': None},
                                          {'name': 'pushToken',
                                           'type': 'string',
                                           'required': False,
                                           'description': 'Push notification token (push)',
                                           'enum': None},
                                          {'name': 'platform',
                                           'type': 'string',
                                           'required': False,
                                           'description': 'Device platform (push)',
                                           'enum': ['ios', 'android']}]},
 'get_alert_contact': {'method': 'GET',
                       'path': '/alert-contacts/{id}',
                       'summary': 'Get a personal alert contact by ID',
                       'category': 'Alert Contacts',
                       'parameters': [{'name': 'id',
                                       'in': 'path',
                                       'required': True,
                                       'type': 'number',
                                       'description': 'ID of the personal alert contact'}],
                       'body_mime': '',
                       'body_required': False,
                       'body_fields': []},
 'update_alert_contact': {'method': 'PATCH',
                          'path': '/alert-contacts/{id}',
                          'summary': 'Update a personal alert contact',
                          'category': 'Alert Contacts',
                          'parameters': [{'name': 'id',
                                          'in': 'path',
                                          'required': True,
                                          'type': 'number',
                                          'description': 'ID of the personal alert contact'}],
                          'body_mime': 'application/json',
                          'body_required': True,
                          'body_fields': [{'name': 'friendlyName',
                                           'type': 'string',
                                           'required': False,
                                           'description': 'Display name of the personal alert '
                                                          'contact',
                                           'enum': None},
                                          {'name': 'enableNotificationsFor',
                                           'type': 'number',
                                           'required': False,
                                           'description': 'Which monitor events this contact is '
                                                          'notified for',
                                           'enum': [0, 1, 2, 3]},
                                          {'name': 'sslExpirationReminder',
                                           'type': 'boolean',
                                           'required': False,
                                           'description': 'Whether to send SSL certificate '
                                                          'expiration reminders',
                                           'enum': None},
                                          {'name': 'isActive',
                                           'type': 'boolean',
                                           'required': False,
                                           'description': 'Activate (true) or pause (false) the '
                                                          'alert contact',
                                           'enum': None}]},
 'delete_alert_contact': {'method': 'DELETE',
                          'path': '/alert-contacts/{id}',
                          'summary': 'Delete a personal alert contact',
                          'category': 'Alert Contacts',
                          'parameters': [{'name': 'id',
                                          'in': 'path',
                                          'required': True,
                                          'type': 'number',
                                          'description': 'ID of the personal alert contact'}],
                          'body_mime': '',
                          'body_required': False,
                          'body_fields': []},
 'list_tags': {'method': 'GET',
               'path': '/tags',
               'summary': 'List user tags',
               'category': 'Tags',
               'parameters': [{'name': 'cursor',
                               'in': 'query',
                               'required': False,
                               'type': 'number',
                               'description': 'Cursor for pagination'}],
               'body_mime': '',
               'body_required': False,
               'body_fields': []},
 'delete_tag': {'method': 'DELETE',
                'path': '/tags/{id}',
                'summary': 'Delete a tag',
                'category': 'Tags',
                'parameters': [{'name': 'id',
                                'in': 'path',
                                'required': True,
                                'type': 'number',
                                'description': 'Tag ID to delete'}],
                'body_mime': '',
                'body_required': False,
                'body_fields': []}}


API_BASE = "https://api.uptimerobot.com/v3"
_PATH_TOKEN = re.compile(r"\{([A-Za-z][A-Za-z0-9]*)\}")


class UptimeRobotApiKeyCredential(BaseModel):
    credential_type: Literal["uptimerobot_api_key"] = Field(
        "uptimerobot_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="Main API Key",
        description="Create a Main API key under Integrations & API in UptimeRobot. Read-only keys cannot perform write operations.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        title="UptimeRobot API Key",
        json_schema_extra={"x-credential-url": "https://dashboard.uptimerobot.com/integrations"}
    )


# UptimeRobot's own MCP server: agents get its tools through a person's UptimeRobot sign-in.
UptimerobotMcpCredential = mcp_credential("uptimerobot", "https://mcp.uptimerobot.com/mcp", app="UptimeRobot")
UptimeRobotCredential = Union[UptimeRobotApiKeyCredential, UptimerobotMcpCredential]


def _field_type(kind: str):
    return {"number": float, "integer": int, "boolean": bool}.get(kind, str)


def _title(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name).replace("_", " ").title()


def _build_operation_model(name: str, spec: Dict[str, Any]):
    fields: Dict[str, Any] = {
        "operation": (
            Literal[name],
            Field(
                name,
                title=_title(name),
                json_schema_extra={
                    "const": name,
                    "ui:hidden": True,
                    "x-category": spec["category"],
                    "x-is-trigger": False,
                    "x-display-name": _title(name),
                },
            ),
        )
    }
    for param in spec["parameters"]:
        key = param["name"] if param["in"] == "path" else f"query_{param['name']}"
        required = param["in"] == "path" or param["required"]
        typ = str if param["in"] == "path" else _field_type(param["type"])
        extra: Dict[str, Any] = {}
        if param["type"] in ("array", "object"):
            extra = {"ui:widget": "code_editor", "x-code-language": "json"}
        fields[key] = (
            typ if required else Optional[typ],
            Field(
                ... if required else None,
                title=_title(param["name"]),
                description=param["description"] or f"{param['in'].title()} parameter: {param['name']}",
                json_schema_extra=extra,
            ),
        )
    for body_field in spec["body_fields"]:
        name_in_body = body_field["name"]
        key = f"body_{name_in_body}"
        # Keep the JSON escape hatch for alternate monitor types and nested
        # payloads. Scalar fields are guided directly in the editor.
        typ = _field_type(body_field["type"])
        required = body_field["required"]
        extra = {}
        if body_field["type"] in ("array", "object"):
            extra = {"ui:widget": "code_editor", "x-code-language": "json"}
        if body_field.get("enum"):
            extra = {**extra, "enum": body_field["enum"], "x-enum-searchable": True}
        fields[key] = (
            typ if required else Optional[typ],
            Field(
                ... if required else None,
                title=_title(name_in_body),
                description=body_field["description"] or f"Request body field: {name_in_body}",
                json_schema_extra=extra,
            ),
        )
    if spec["body_mime"]:
        fields["body_json"] = (
            Optional[str],
            Field(
                None,
                title="Additional Body Fields (JSON)",
                description="Full or additional request body as a JSON object. Guided fields override matching keys.",
                json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
            ),
        )
    model_name = "UptimeRobot" + "".join(part.title() for part in name.split("_")) + "Config"
    return create_model(model_name, __module__=__name__, **fields)


_CONFIG_MODELS = [_build_operation_model(name, spec) for name, spec in OPERATIONS.items()]
UptimeRobotConfig = Annotated[Union[tuple(_CONFIG_MODELS)], Discriminator("operation")]


class UptimeRobotNodeConfig(NodeConfig[UptimeRobotConfig, UptimeRobotCredential]):
    pass


def _json_object(value: str, field: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field} must contain valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field} must contain a JSON object")
    return parsed


def _json_value(value: str, field: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field} must contain valid JSON") from exc


def _request_parts(operation: BaseModel, spec: Dict[str, Any]):
    values = operation.model_dump(exclude_none=True)
    path = spec["path"]
    for token in _PATH_TOKEN.findall(path):
        raw = str(values.get(token, "")).strip()
        if not raw:
            raise ValueError(f"{token} is required")
        # Encode each path segment so an injected slash cannot change endpoint.
        path = path.replace("{" + token + "}", quote(raw, safe=""))
    params = {}
    for param in spec["parameters"]:
        if param["in"] != "query":
            continue
        key = f"query_{param['name']}"
        value = values.get(key)
        if value is None or value == "":
            continue
        if param["type"] in ("array", "object"):
            value = _json_value(value, key)
        params[param["name"]] = value
    body = None
    if spec["body_mime"]:
        body = _json_object(values["body_json"], "body_json") if values.get("body_json") else {}
        for field in spec["body_fields"]:
            key = f"body_{field['name']}"
            value = values.get(key)
            if value is None or value == "":
                continue
            if field["type"] in ("array", "object"):
                value = _json_value(value, key)
            body[field["name"]] = value
        if operation.operation == "create_monitor" and body.get("type") in {"HTTP", "KEYWORD", "PORT"}:
            # The published schema marks timeout optional, but the live v3
            # endpoint rejects an omitted value for these monitor types.
            body.setdefault("timeout", 30)
    return path, params, body


async def _uptimerobot_request(
    api_key: str,
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    mime: str = "",
) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    kwargs: Dict[str, Any] = {"params": params or None}
    if mime == "multipart/form-data":
        # The v3 PSP form accepts text fields in multipart bodies. File fields
        # (logo/icon) are intentionally absent from the operation catalog.
        kwargs["files"] = {
            key: (None, json.dumps(value) if isinstance(value, (dict, list)) else str(value))
            for key, value in (body or {}).items()
        }
    elif body is not None:
        kwargs["json"] = body
    # Pause/start/reset accept an optional empty JSON body, and the published
    # schema explicitly asks for Content-Type even if the body is empty.
    if method == "POST" and body is None and path.endswith(("/pause", "/start", "/reset")):
        kwargs["json"] = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(method, f"{API_BASE}{path}", headers=headers, **kwargs)
        except httpx.RequestError as exc:
            return {"status": "error", "error": f"Network request failed: {type(exc).__name__}"}
    try:
        payload = response.json() if response.content else None
    except ValueError:
        payload = response.text
    if response.status_code >= 400:
        message = payload.get("message") or payload.get("error") if isinstance(payload, dict) else payload
        return {
            "status": "error",
            "status_code": response.status_code,
            "error": str(message or response.reason_phrase)[:1000],
            "retry_after": response.headers.get("Retry-After") if response.status_code == 429 else None,
        }
    return {"status": "success", "status_code": response.status_code, "data": payload}


class UptimeRobotNode(WorkflowNode):
    """UptimeRobot monitor and incident automation."""

    integration_type = "automation-uptimerobot"

    credential_provider_labels = {"uptimerobot": "UptimeRobot Account"}

    connection_evidence = ConnectionEvidence(
        operation="list_monitors",
        noun="monitors",
        label_keys=("friendlyName", "name", "id"),
        identity_operation="get_current_user",
    )
    edit_examples = [
        "List my monitors and their current status",
        "Create a monitor for the production API",
        "Pause a monitor during a deployment",
        "List recent incidents and their alert history",
        "Create a maintenance window for the deployment",
    ]

    @classmethod
    def get_config_model(cls):
        return UptimeRobotNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, UptimeRobotNodeConfig):
            raise ValueError("Valid UptimeRobot configuration is required")
        credential = self.config.credentials
        if not credential or not credential.api_key:
            raise ValueError("Connect a UptimeRobot Main API key")
        operation = self.config.config
        name = operation.operation
        spec = OPERATIONS[name]
        path, params, body = _request_parts(operation, spec)
        start = time.monotonic()
        result = await _uptimerobot_request(
            credential.api_key, spec["method"], path,
            params=params, body=body, mime=spec["body_mime"],
        )
        result["operation"] = name
        result["timing_ms"] = {"api_request": round((time.monotonic() - start) * 1000, 2)}
        return result
