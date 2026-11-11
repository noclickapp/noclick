"""SuprSend OpenAPI 1.2.2 endpoint and field mapping.

Source: https://docs.suprsend.com/openapi.yaml
Complex values are JSON editor fields; each operation makes one provider request.
"""

OPERATIONS = {'trigger_event': {'id': 'event-api',
                   'method': 'POST',
                   'path': '/event/',
                   'label': 'Trigger an Event',
                   'fields': {'distinct_id': {'wire': 'distinct_id',
                                              'in': 'body',
                                              'type': 'string',
                                              'required': True,
                                              'description': 'distinct_id of recipient who should receive '
                                                             'the notification'},
                              'event': {'wire': 'event',
                                        'in': 'body',
                                        'type': 'string',
                                        'required': True,
                                        'description': 'string identifier for the event like '
                                                       '`product_purchased`'},
                              'properties_json': {'wire': 'properties',
                                                  'in': 'body',
                                                  'type': 'object',
                                                  'required': False,
                                                  'description': 'Properties are used to render template or '
                                                                 'workflow variables in the trigger.'},
                              'tenant_id': {'wire': 'tenant_id',
                                            'in': 'body',
                                            'type': 'string',
                                            'required': False,
                                            'description': 'string identifier of the tenant this event is '
                                                           'associated with'},
                              'idempotency_key': {'wire': '$idempotency_key',
                                                  'in': 'body',
                                                  'type': 'string',
                                                  'required': False,
                                                  'description': 'Idempotency key (valid for 24hours)'},
                              'cancellation_key': {'wire': 'cancellation_key',
                                                   'in': 'body',
                                                   'type': 'string',
                                                   'required': False,
                                                   'description': 'Lookup key stored on each execution this '
                                                                  'event triggers, so a [Cancel '
                                                                  'Workflow](/docs/cancel-workflow) node can '
                                                                  'later stop them by matching on it. Pass a '
                                                                  'literal string (max 512 characters; '
                                                                  'longer values are truncated). Overrides a '
                                                                  "target workflow's own Trigger-node "
                                                                  'Cancellation Key expression when both are '
                                                                  'present.',
                                                   'maxLength': 512}}},
 'trigger_workflow': {'id': 'trigger-workflow-api',
                      'method': 'POST',
                      'path': '/trigger/',
                      'label': 'Trigger Workflow',
                      'fields': {'workflow': {'wire': 'workflow',
                                              'in': 'body',
                                              'type': 'string',
                                              'required': True,
                                              'description': 'You can get workflow slug from workflow '
                                                             'settings on SuprSend dashboard.'},
                                 'recipients_json': {'wire': 'recipients',
                                                     'in': 'body',
                                                     'type': 'array',
                                                     'required': True,
                                                     'description': 'List of recipients to be notified. You '
                                                                    'can either add recipient as array of '
                                                                    'distinct_ids or array of recipient '
                                                                    'objects. You can add up to 100 '
                                                                    'recipients in a single API.'},
                                 'actor_json': {'wire': 'actor',
                                                'in': 'body',
                                                'type': 'object',
                                                'required': False,
                                                'description': 'Includes distinct_id and properties of the '
                                                               'user who performed the action. You can use '
                                                               'it for [cross-user '
                                                               'notifications]("https://docs.suprsend.com/docs/trigger-workflow#sending-cross-user-notifications"). '
                                                               'Actor properties can be added as '
                                                               '`$actor.<prop>`.'},
                                 'data_json': {'wire': 'data',
                                               'in': 'body',
                                               'type': 'object',
                                               'required': False,
                                               'description': 'variable data required to render dynamic '
                                                              'template content or workflow properties like '
                                                              'dynamic delay or channel override in send '
                                                              'node.'},
                                 'tenant_id': {'wire': 'tenant_id',
                                               'in': 'body',
                                               'type': 'string',
                                               'required': False,
                                               'description': 'Tenant context for this trigger. Applies the '
                                                              "tenant's branding, admin preferences, and "
                                                              'vendor routing, and — for users with a '
                                                              '[per-tenant '
                                                              'profile](/docs/user-tenant-mapping) — '
                                                              'resolves recipients against the merged '
                                                              '(global + per-tenant) profile.'},
                                 'idempotency_key': {'wire': '$idempotency_key',
                                                     'in': 'body',
                                                     'type': 'string',
                                                     'required': False,
                                                     'description': 'Idempotency_key (valid for 24hrs)'},
                                 'cancellation_key': {'wire': 'cancellation_key',
                                                      'in': 'body',
                                                      'type': 'string',
                                                      'required': False,
                                                      'description': 'Lookup key stored on the running '
                                                                     'execution so a [Cancel '
                                                                     'Workflow](/docs/cancel-workflow) node '
                                                                     'can later stop this run by matching on '
                                                                     'it. Pass a literal string (max 512 '
                                                                     'characters; longer values are '
                                                                     'truncated). When both this field and '
                                                                     "the target workflow's Trigger-node "
                                                                     'Cancellation Key JSONNET expression '
                                                                     'are present, this payload value wins.',
                                                      'maxLength': 512}}},
 'trigger_workflow_on_list': {'id': 'trigger-workflow-on-list',
                              'method': 'POST',
                              'path': '/trigger/list/',
                              'label': 'Trigger Workflow on a List',
                              'fields': {'list_id': {'wire': 'list_id',
                                                     'in': 'body',
                                                     'type': 'string',
                                                     'required': True,
                                                     'description': 'ID of the list whose users you want to '
                                                                    'notify. Case-insensitive. The list must '
                                                                    'exist and be enabled.'},
                                         'workflow': {'wire': 'workflow',
                                                      'in': 'body',
                                                      'type': 'string',
                                                      'required': True,
                                                      'description': 'Slug of the workflow to trigger. The '
                                                                     'workflow must exist in the workspace.'},
                                         'data_json': {'wire': 'data',
                                                       'in': 'body',
                                                       'type': 'object',
                                                       'required': False,
                                                       'description': 'Variables used in the workflow and '
                                                                      'its templates, as `{{key}}`. The same '
                                                                      "`data` goes to every list member's "
                                                                      'run. Use `$recipient.<property>` in '
                                                                      'templates for per-user values.'},
                                         'tenant_id': {'wire': 'tenant_id',
                                                       'in': 'body',
                                                       'type': 'string',
                                                       'required': False,
                                                       'description': 'ID of the [tenant](/docs/tenants) the '
                                                                      'runs belong to. Its branding and '
                                                                      'preferences apply to every run. '
                                                                      'Defaults to `default`. The tenant '
                                                                      'must exist.'},
                                         'delay': {'wire': 'delay',
                                                   'in': 'body',
                                                   'type': 'string',
                                                   'required': False,
                                                   'description': 'Wait this long before triggering. Pass a '
                                                                  'duration string in the format '
                                                                  '`XXdXXhXXmXXs` (for example, `1h30m`) or '
                                                                  'a number of seconds (for example, '
                                                                  '`5400`). Maximum 15 days.\n'},
                                         'trigger_at': {'wire': 'trigger_at',
                                                        'in': 'body',
                                                        'type': 'string',
                                                        'required': False,
                                                        'description': 'Trigger at this date-time, in ISO '
                                                                       '8601 format with a timezone (for '
                                                                       'example, `2026-11-05T09:30:00Z`). '
                                                                       'Maximum 15 days from now. If '
                                                                       '`trigger_at` is in the future, it '
                                                                       "wins over `delay`. If it's in the "
                                                                       'past, `delay` applies when set; '
                                                                       'otherwise the workflow triggers '
                                                                       'right away.\n'},
                                         'cancellation_key': {'wire': 'cancellation_key',
                                                              'in': 'body',
                                                              'type': 'string',
                                                              'required': False,
                                                              'description': 'Key stored on every run '
                                                                             'started by this trigger, so a '
                                                                             '[Cancel '
                                                                             'Workflow](/docs/cancel-workflow) '
                                                                             'node can stop those runs. This '
                                                                             "value overrides the workflow's "
                                                                             'Trigger-node cancellation key '
                                                                             'expression. To cancel the runs '
                                                                             'through the [Cancel Workflow '
                                                                             'API](/reference/cancel-workflow) '
                                                                             "instead, pass this request's "
                                                                             '`$idempotency_key` (or the '
                                                                             '`message_id` from the '
                                                                             'response) as '
                                                                             '`idempotency_key`.',
                                                              'maxLength': 512},
                                         'idempotency_key': {'wire': '$idempotency_key',
                                                             'in': 'body',
                                                             'type': 'string',
                                                             'required': False,
                                                             'description': 'Unique key for this request, up '
                                                                            'to 255 characters. Another '
                                                                            'request with the same key '
                                                                            'within 24 hours is ignored, so '
                                                                            "retries don't notify the list "
                                                                            'twice.'}}},
 'cancel_workflow': {'id': 'cancel-workflow',
                     'method': 'POST',
                     'path': '/v1/workflow_run/cancel/',
                     'label': 'Cancel Workflow',
                     'fields': {'execution_id': {'wire': 'execution_id',
                                                 'in': 'body',
                                                 'type': 'string',
                                                 'required': False,
                                                 'description': 'Unique execution identifier of the workflow '
                                                                'run to cancel. You can find this in the '
                                                                'workflow logs on the SuprSend dashboard.'},
                                'recipients_json': {'wire': 'recipients',
                                                    'in': 'body',
                                                    'type': 'array',
                                                    'required': False,
                                                    'description': 'List of recipient `distinct_id`s whose '
                                                                   'workflow runs should be cancelled.'},
                                'idempotency_key': {'wire': 'idempotency_key',
                                                    'in': 'body',
                                                    'type': 'string',
                                                    'required': False,
                                                    'description': 'Idempotency key that was passed when '
                                                                   'triggering the workflow. Use this to '
                                                                   'cancel a specific workflow triggered '
                                                                   'with a known idempotency key.'},
                                'workflow': {'wire': 'workflow',
                                             'in': 'body',
                                             'type': 'string',
                                             'required': False,
                                             'description': 'Slug of the workflow whose runs should be '
                                                            'cancelled.'}}},
 'upsert_user': {'id': 'create-update-users',
                 'method': 'POST',
                 'path': '/v1/user/{distinct_id}/',
                 'label': 'Create / Update Users',
                 'fields': {'distinct_id': {'wire': 'distinct_id',
                                            'in': 'path',
                                            'type': 'string',
                                            'required': True,
                                            'description': 'Unique identifier of the user in your system'},
                            'payload_json': {'wire': None,
                                             'in': 'body',
                                             'type': 'object',
                                             'required': True,
                                             'description': 'JSON object matching the documented Create / '
                                                            'Update Users payload. Use $email, $sms, '
                                                            '$timezone and custom profile properties.'}}},
 'get_user': {'id': 'fetch-user-profile',
              'method': 'GET',
              'path': '/v1/user/{distinct_id}/',
              'label': 'Fetch User by id',
              'fields': {'distinct_id': {'wire': 'distinct_id',
                                         'in': 'path',
                                         'type': 'string',
                                         'required': True,
                                         'description': 'Unique identifier of the user in your system'}}},
 'update_user': {'id': 'edit-user-profile',
                 'method': 'PATCH',
                 'path': '/v1/user/{distinct_id}/',
                 'label': 'Edit User Profile',
                 'fields': {'distinct_id': {'wire': 'distinct_id',
                                            'in': 'path',
                                            'type': 'string',
                                            'required': True,
                                            'description': 'unique identifier of the user'},
                            'operations_json': {'wire': 'operations',
                                                'in': 'body',
                                                'type': 'array',
                                                'required': False,
                                                'description': 'You can use the following operations to edit '
                                                               'user profile.\n'
                                                               '- `$set` to add/update a property\n'
                                                               '- `$unset` to delete property/channel\n'
                                                               '- `$append` to insert values in '
                                                               'property/channel array\n'
                                                               '- `$remove` to remove values from '
                                                               'property/channel array\n'
                                                               '- `$set_once` to set immutable properties '
                                                               "(only set if the property doesn't already "
                                                               'exist)\n'
                                                               '- `$add` to increase/decrease integer values '
                                                               'on further update\n'}}},
 'delete_user': {'id': 'delete-user',
                 'method': 'DELETE',
                 'path': '/v1/user/{distinct_id}/',
                 'label': 'Delete user',
                 'fields': {'distinct_id': {'wire': 'distinct_id',
                                            'in': 'path',
                                            'type': 'string',
                                            'required': True,
                                            'description': 'Unique identifier of the user in your system'}}},
 'list_users': {'id': 'list-users',
                'method': 'GET',
                'path': '/v1/user/',
                'label': 'List Users',
                'fields': {'limit': {'wire': 'limit',
                                     'in': 'query',
                                     'type': 'integer',
                                     'required': False,
                                     'description': 'number of results to be returned in API response (max '
                                                    '100)',
                                     'default': 10,
                                     'minimum': 1,
                                     'maximum': 100},
                           'after': {'wire': 'after',
                                     'in': 'query',
                                     'type': 'string',
                                     'required': False,
                                     'description': 'cursor to fetch the next page (from `meta.after` of the '
                                                    'previous response)'},
                           'before': {'wire': 'before',
                                      'in': 'query',
                                      'type': 'string',
                                      'required': False,
                                      'description': 'cursor to fetch the previous page (from `meta.before` '
                                                     'of the previous response)'},
                           'tenant_id': {'wire': 'tenant_id',
                                         'in': 'query',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'Filter users associated with the given tenant. When '
                                                        'set, each result includes the tenant-scoped '
                                                        '`properties` and channel overrides applied for this '
                                                        'user under that tenant.'}}},
 'create_list': {'id': 'create-list',
                 'method': 'POST',
                 'path': '/v1/subscriber_list/',
                 'label': 'Create a List',
                 'fields': {'list_id': {'wire': 'list_id',
                                        'in': 'body',
                                        'type': 'string',
                                        'required': True,
                                        'description': 'Unique string identifier of the list. Add an id '
                                                       'which defines the type of users who are part of the '
                                                       'list. Allowed characters: lowercase letters, digits, '
                                                       'hyphens, and underscores.',
                                        'pattern': '^[a-z0-9_-]+$'},
                            'list_name': {'wire': 'list_name',
                                          'in': 'body',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'Name of the List. Add a name which defines the '
                                                         'type of users in the list.'},
                            'list_description': {'wire': 'list_description',
                                                 'in': 'body',
                                                 'type': 'string',
                                                 'required': False,
                                                 'description': 'Brief description of the list and the type '
                                                                'of users in it.'},
                            'list_type': {'wire': 'list_type',
                                          'in': 'body',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'Type of the list. Use `dynamic_list` to create a '
                                                         '[Segment List](/docs/segment-lists) whose '
                                                         'membership is driven by a SQL query. Defaults to '
                                                         '`static_list`.',
                                          'enum': ['static_list', 'dynamic_list']},
                            'query': {'wire': 'query',
                                      'in': 'body',
                                      'type': 'string',
                                      'required': False,
                                      'description': 'SQL query defining the segment. **Needed for a '
                                                     '`dynamic_list` to sync** — if omitted, the list is '
                                                     'created but its segment sync stays disabled. Must '
                                                     'return a `distinct_id` column and reference only the '
                                                     '`users` and `events` tables. See the [Segment Lists '
                                                     'doc](/docs/segment-lists) for the full dialect '
                                                     'reference.'},
                            'is_enabled': {'wire': 'is_enabled',
                                           'in': 'body',
                                           'type': 'boolean',
                                           'required': False,
                                           'description': 'Only applies to `dynamic_list`. When `true`, the '
                                                          'segment starts syncing immediately after create. '
                                                          'When `false`, the query is saved but the segment '
                                                          'does not refresh until you enable it.'}}},
 'list_lists': {'id': 'get-all-lists',
                'method': 'GET',
                'path': '/v1/subscriber_list/',
                'label': 'Get all Lists',
                'fields': {'limit': {'wire': 'limit',
                                     'in': 'query',
                                     'type': 'integer',
                                     'required': False,
                                     'description': 'number of results to be returned in API response',
                                     'default': 20,
                                     'minimum': 1,
                                     'maximum': 100},
                           'offset': {'wire': 'offset',
                                      'in': 'query',
                                      'type': 'integer',
                                      'required': False,
                                      'description': 'starting position of the lists to return',
                                      'default': 0,
                                      'minimum': 0,
                                      'maximum': 1000000}}},
 'get_list': {'id': 'get-list',
              'method': 'GET',
              'path': '/v1/subscriber_list/{list_id}/',
              'label': 'Get List configuration',
              'fields': {'list_id': {'wire': 'list_id',
                                     'in': 'path',
                                     'type': 'string',
                                     'required': True,
                                     'description': 'Unique string identifier of the list.',
                                     'pattern': '^[a-z0-9_-]+$'}}},
 'add_list_users': {'id': 'add-subscribers-to-list',
                    'method': 'POST',
                    'path': '/v1/subscriber_list/{list_id}/subscriber/add/',
                    'label': 'Add Users to List',
                    'fields': {'list_id': {'wire': 'list_id',
                                           'in': 'path',
                                           'type': 'string',
                                           'required': True,
                                           'description': 'Unique string identifier of the list to which '
                                                          'user needs to be updated',
                                           'pattern': '^[a-z0-9_-]+$'},
                               'distinct_ids_json': {'wire': 'distinct_ids',
                                                     'in': 'body',
                                                     'type': 'array',
                                                     'required': False,
                                                     'description': 'Array of subscriber_ids, uniquely '
                                                                    'identifying the subscribers to be added '
                                                                    'to the list.'}}},
 'remove_list_users': {'id': 'remove-users-from-list',
                       'method': 'POST',
                       'path': '/v1/subscriber_list/{list_id}/subscriber/remove/',
                       'label': 'Remove Subscribers from List',
                       'fields': {'list_id': {'wire': 'list_id',
                                              'in': 'path',
                                              'type': 'string',
                                              'required': True,
                                              'description': 'Unique string identifier of the list to which '
                                                             'user needs to be updated',
                                              'pattern': '^[a-z0-9_-]+$'},
                                  'distinct_ids_json': {'wire': 'distinct_ids',
                                                        'in': 'body',
                                                        'type': 'array',
                                                        'required': False,
                                                        'description': 'Array of subscriber_ids, uniquely '
                                                                       'identifying the subscribers to be '
                                                                       'removed from the list.'}}},
 'list_list_users': {'id': 'get-subscriber-list-users',
                     'method': 'GET',
                     'path': '/v1/subscriber_list/{list_id}/subscriber/',
                     'label': 'Get list subscribers',
                     'fields': {'list_id': {'wire': 'list_id',
                                            'in': 'path',
                                            'type': 'string',
                                            'required': True,
                                            'description': 'The list_id of your subscriber list',
                                            'pattern': '^[a-z0-9_-]+$'},
                                'limit': {'wire': 'limit',
                                          'in': 'query',
                                          'type': 'integer',
                                          'required': False,
                                          'description': 'limit',
                                          'default': 20,
                                          'minimum': 1,
                                          'maximum': 100},
                                'before': {'wire': 'before',
                                           'in': 'query',
                                           'type': 'string',
                                           'required': False,
                                           'description': "the 'id' before which the results need to be "
                                                          'fetched'},
                                'after': {'wire': 'after',
                                          'in': 'query',
                                          'type': 'string',
                                          'required': False,
                                          'description': "the 'id' after which the results need to be "
                                                         'fetched'},
                                'sort': {'wire': 'sort',
                                         'in': 'query',
                                         'type': 'string',
                                         'required': False,
                                         'description': "the sort order, ascending or descending, here it's "
                                                        "decided by 'id': ascending and '-id': descending"}}},
 'upsert_tenant': {'id': 'create-tenants',
                   'method': 'POST',
                   'path': '/v1/tenant/{tenant_id}/',
                   'label': 'Create / Update Tenants',
                   'fields': {'tenant_id': {'wire': 'tenant_id',
                                            'in': 'path',
                                            'type': 'string',
                                            'required': True,
                                            'description': 'Tenant identifier to create or update. Max 64 '
                                                           'chars; allowed characters `[a-zA-Z0-9_.-]` '
                                                           '(converted to lowercase unless case-sensitive '
                                                           'IDs are enabled for your organization).',
                                            'pattern': '^[a-zA-Z0-9_.-]+$',
                                            'maxLength': 64},
                              'name': {'wire': 'name',
                                       'in': 'body',
                                       'type': 'string',
                                       'required': True,
                                       'description': 'Tenant display name. Replaces the legacy '
                                                      '`tenant_name` field; both are accepted.'},
                              'parent_id': {'wire': 'parent_id',
                                            'in': 'body',
                                            'type': 'string',
                                            'required': False,
                                            'description': 'ID of the parent tenant if you want to add this '
                                                           'tenant as a sub-tenant. Skip this field, or pass '
                                                           '`null` or `""` to create the tenant as a root. '
                                                           'Setting it on an existing tenant re-parents it '
                                                           'or leave it `null` to delink existing parent. '
                                                           'Must reference an existing tenant. See '
                                                           '[Sub-tenants](/docs/sub-tenants).'},
                              'blocked_channels_json': {'wire': 'blocked_channels',
                                                        'in': 'body',
                                                        'type': 'array',
                                                        'required': False,
                                                        'description': 'Channels turned off for this tenant. '
                                                                       'Notifications on these channels '
                                                                       "won't be sent to any user of the "
                                                                       'tenant — including on [root '
                                                                       'categories](/docs/notification-category#root-categories) '
                                                                       "(which users normally can't "
                                                                       "unsubscribe from) — and users can't "
                                                                       'override this. If '
                                                                       '[sub-tenants](/docs/sub-tenants) are '
                                                                       'used, a block set here also applies '
                                                                       "to every sub-tenant below and can't "
                                                                       'be removed lower down. Allowed: '
                                                                       '`email`, `sms`, `whatsapp`, '
                                                                       '`androidpush`, `iospush`, `webpush`, '
                                                                       '`slack`, `ms_teams`, `inbox`.'},
                              'logo': {'wire': 'logo',
                                       'in': 'body',
                                       'type': 'string',
                                       'required': False,
                                       'description': 'Tenant logo URL.'},
                              'primary_color': {'wire': 'primary_color',
                                                'in': 'body',
                                                'type': 'string',
                                                'required': False,
                                                'description': "Primary brand color, used in the tenant's "
                                                               'email header, buttons, and footer. If left '
                                                               "empty when creating a root tenant, it's set "
                                                               "to SuprSend's default (`#777777`)."},
                              'secondary_color': {'wire': 'secondary_color',
                                                  'in': 'body',
                                                  'type': 'string',
                                                  'required': False,
                                                  'description': 'Secondary brand color. Not part of the '
                                                                 'default tenant component but can be used '
                                                                 'in templates as '
                                                                 '`{{$tenant.secondary_color}}`. If both '
                                                                 'secondary and tertiary colors are left '
                                                                 "empty when creating a root tenant, they're "
                                                                 'copied from the default tenant.'},
                              'tertiary_color': {'wire': 'tertiary_color',
                                                 'in': 'body',
                                                 'type': 'string',
                                                 'required': False,
                                                 'description': 'Tertiary brand color. Not part of the '
                                                                'default tenant component but can be used in '
                                                                'templates as `{{$tenant.tertiary_color}}`. '
                                                                'If both secondary and tertiary colors are '
                                                                'left empty when creating a root tenant, '
                                                                "they're copied from the default tenant."},
                              'embedded_preference_url': {'wire': 'embedded_preference_url',
                                                          'in': 'body',
                                                          'type': 'string',
                                                          'required': False,
                                                          'description': "URL of your product's preference "
                                                                         'page.'},
                              'social_links_json': {'wire': 'social_links',
                                                    'in': 'body',
                                                    'type': 'object',
                                                    'required': False,
                                                    'description': 'Tenant\'s social media URLs. Pass `""` '
                                                                   'to clear a link (not `null`).'},
                              'properties_json': {'wire': 'properties',
                                                  'in': 'body',
                                                  'type': 'object',
                                                  'required': False,
                                                  'description': 'Custom tenant properties. Merged per '
                                                                 'top-level key on update — keys not in the '
                                                                 'payload are kept as-is.'}}},
 'get_tenant': {'id': 'get-tenant',
                'method': 'GET',
                'path': '/v1/tenant/{tenant_id}/',
                'label': 'Get Tenant',
                'fields': {'tenant_id': {'wire': 'tenant_id',
                                         'in': 'path',
                                         'type': 'string',
                                         'required': True,
                                         'description': 'unique identifier of the tenant you want to get the '
                                                        'details for'}}},
 'list_tenants': {'id': 'get-tenant-list',
                  'method': 'GET',
                  'path': '/v1/tenant/',
                  'label': 'List Tenants',
                  'fields': {'limit': {'wire': 'limit',
                                       'in': 'query',
                                       'type': 'integer',
                                       'required': False,
                                       'description': 'Number of tenants to return per page.',
                                       'default': 10,
                                       'minimum': 1,
                                       'maximum': 100},
                             'offset': {'wire': 'offset',
                                        'in': 'query',
                                        'type': 'integer',
                                        'required': False,
                                        'description': 'Number of tenants to skip.',
                                        'default': 0,
                                        'minimum': 0,
                                        'maximum': 1000000},
                             'parent_id': {'wire': 'parent_id',
                                           'in': 'query',
                                           'type': 'string',
                                           'required': False,
                                           'description': 'Returns only direct children of the given '
                                                          'tenant.'},
                             'ancestors_json': {'wire': 'ancestor[]',
                                                'in': 'query',
                                                'type': 'array',
                                                'required': False,
                                                'description': 'Returns all descendants (at any depth) of '
                                                               'the given tenant. The tenant itself is not '
                                                               'included. Repeat the param to pass multiple '
                                                               'tenants.'},
                             'levels_json': {'wire': 'level[]',
                                             'in': 'query',
                                             'type': 'array',
                                             'required': False,
                                             'description': 'Returns tenants at the given level(s). Root = '
                                                            '0, max = 4. Repeat the param to combine '
                                                            'levels.'}}},
 'update_tenant_properties': {'id': 'update-tenant-properties',
                              'method': 'PATCH',
                              'path': '/v1/tenant/{tenant_id}/properties/',
                              'label': 'Update Tenant Properties',
                              'fields': {'tenant_id': {'wire': 'tenant_id',
                                                       'in': 'path',
                                                       'type': 'string',
                                                       'required': True,
                                                       'description': 'unique identifier of the tenant whose '
                                                                      'properties you want to update'},
                                         'payload_json': {'wire': None,
                                                          'in': 'body',
                                                          'type': 'object',
                                                          'required': True,
                                                          'description': 'JSON object matching the '
                                                                         'documented Update Tenant '
                                                                         'Properties payload. Use either '
                                                                         'properties to replace all custom '
                                                                         'properties, or operations with '
                                                                         '$set / $unset.'}}},
 'get_user_preferences': {'id': 'get-user-full-preference',
                          'method': 'GET',
                          'path': '/v1/user/{distinct_id}/preference/',
                          'label': 'Get User Preferences',
                          'fields': {'distinct_id': {'wire': 'distinct_id',
                                                     'in': 'path',
                                                     'type': 'string',
                                                     'required': True,
                                                     'description': 'distinct_id of the user whose '
                                                                    'preferences should be fetched'},
                                     'tenant_id': {'wire': 'tenant_id',
                                                   'in': 'query',
                                                   'type': 'string',
                                                   'required': False,
                                                   'description': 'to fetch user preferences for a '
                                                                  'particular tenant'},
                                     'show_opt_out_channels': {'wire': 'show_opt_out_channels',
                                                               'in': 'query',
                                                               'type': 'boolean',
                                                               'required': False,
                                                               'description': 'set this flag to `true` if '
                                                                              'you want to fetch channel '
                                                                              'list for opt-out categories.'},
                                     'tags': {'wire': 'tags',
                                              'in': 'query',
                                              'type': 'string',
                                              'required': False,
                                              'description': 'Filter preference categories with tags '
                                                             'assigned to them. Used to filter preference '
                                                             'categories relevant to the user on UI based on '
                                                             'their roles, department or teams.\n'
                                                             'You can apply single tag filter like '
                                                             '`tags=tag1` or build nested conditions using '
                                                             'logical operators - `and`, `or`, `not`, '
                                                             '`exists`.\n'
                                                             '\n'
                                                             'Example:\n'
                                                             '```\n'
                                                             'tags=admin\n'
                                                             'tags={"or":[{"and":["admin","sales"]},{"and":["admin","manager"]}]}\n'
                                                             'tags={"not":"admin"}\n'
                                                             'tags={"exists":true}\n'},
                                     'locale': {'wire': 'locale',
                                                'in': 'query',
                                                'type': 'string',
                                                'required': False,
                                                'description': 'Locale code (e.g., `es`, `fr`, `es-AR`) to '
                                                               "fetch preference translations in user's "
                                                               'locale. When provided, the API looks for '
                                                               'category and section names and descriptions '
                                                               'in the respective locale file.\n'
                                                               'If a translation is missing for the '
                                                               'requested locale, the system automatically '
                                                               'falls back in this order: `locale-region` '
                                                               '(e.g., `es-AR`) → `locale` (e.g., `es`) → '
                                                               '`en` (English - always available).\n'}}},
 'update_user_preferences': {'id': 'update-user-full-preference',
                             'method': 'PATCH',
                             'path': '/v1/user/{distinct_id}/preference/',
                             'label': 'Update User Full Preference',
                             'fields': {'distinct_id': {'wire': 'distinct_id',
                                                        'in': 'path',
                                                        'type': 'string',
                                                        'required': True,
                                                        'description': 'distinct_id of the user whose '
                                                                       'preferences should be updated'},
                                        'tenant_id': {'wire': 'tenant_id',
                                                      'in': 'query',
                                                      'type': 'string',
                                                      'required': False,
                                                      'description': 'to update user preferences for a '
                                                                     'particular tenant'},
                                        'channel_preferences_json': {'wire': 'channel_preferences',
                                                                     'in': 'body',
                                                                     'type': 'array',
                                                                     'required': False,
                                                                     'description': 'Use this to update '
                                                                                    'channel level user '
                                                                                    'preferences. Set '
                                                                                    '`is_restricted - true` '
                                                                                    'if the channel is '
                                                                                    'opted_out by the user. '
                                                                                    'This will only send '
                                                                                    'critical notifications '
                                                                                    "to the user which can't "
                                                                                    'be opted out'},
                                        'categories_json': {'wire': 'categories',
                                                            'in': 'body',
                                                            'type': 'array',
                                                            'required': False,
                                                            'description': 'Use this to update user '
                                                                           'preference across categories and '
                                                                           'channels inside a category.'}}},
 'list_templates': {'id': 'fetch-template-list',
                    'method': 'GET',
                    'path': '/v1/template/',
                    'label': 'Fetch Template List',
                    'fields': {'has_tags_any': {'wire': 'has_tags_any',
                                                'in': 'query',
                                                'type': 'string',
                                                'required': False,
                                                'description': 'comma separated string of tag names attached '
                                                               'to the template. Returns templates that have '
                                                               'any of the given tags.'},
                               'has_channels_any': {'wire': 'has_channels_any',
                                                    'in': 'query',
                                                    'type': 'string',
                                                    'required': False,
                                                    'description': 'comma separated string of channels. '
                                                                   'Returns templates which has any of the '
                                                                   'channels present from the channel '
                                                                   'string. Use these keys for channels - '
                                                                   '`email`, `sms`, `whatsapp`, `inbox`, '
                                                                   '`slack`, `androidpush`, `iospush`, '
                                                                   '`webpush`'},
                               'is_active': {'wire': 'is_active',
                                             'in': 'query',
                                             'type': 'boolean',
                                             'required': False,
                                             'description': 'Set `true` for published templates, `false` for '
                                                            'templates which are in draft. Do not pass this '
                                                            'key to return all templates.'},
                               'is_archived': {'wire': 'is_archived',
                                               'in': 'query',
                                               'type': 'boolean',
                                               'required': False,
                                               'description': 'Set `true` to get archived templates, default '
                                                              '= `false`'}}},
 'get_template': {'id': 'fetch-template-details',
                  'method': 'GET',
                  'path': '/v1/template/{template_slug}/',
                  'label': 'Fetch Template details',
                  'fields': {'template_slug': {'wire': 'template_slug',
                                               'in': 'path',
                                               'type': 'string',
                                               'required': True,
                                               'description': 'Template group slug you want to fetch content '
                                                              "details. You'll get the template slug by "
                                                              'clicking on copy button next to template '
                                                              'group name on SuprSend dashboard -> template '
                                                              'details page.'}}},
 'list_messages': {'id': 'list-messages',
                   'method': 'GET',
                   'path': '/v1/message/',
                   'label': 'List Messages',
                   'fields': {'limit': {'wire': 'limit',
                                        'in': 'query',
                                        'type': 'integer',
                                        'required': False,
                                        'description': 'Maximum number of messages to return per page. '
                                                       'Defaults to `10`, maximum is `1000` (`20` when '
                                                       '`include_content=true`). Larger values are capped to '
                                                       'the maximum.',
                                        'maximum': 100,
                                        'default': 10,
                                        'minimum': 1},
                              'after': {'wire': 'after',
                                        'in': 'query',
                                        'type': 'string',
                                        'required': False,
                                        'description': 'Cursor for forward pagination - pass the '
                                                       '`meta.after` value from a previous response to fetch '
                                                       'the next page of older messages. Treat this value as '
                                                       'an opaque cursor - do not parse, validate, or assume '
                                                       'any format for it. **Takes precedence over `before` '
                                                       'when both are set** (`before` is silently '
                                                       'ignored).\n'},
                              'before': {'wire': 'before',
                                         'in': 'query',
                                         'type': 'string',
                                         'required': False,
                                         'description': 'Cursor for backward pagination - pass the '
                                                        '`meta.before` value from a previous response to '
                                                        'fetch the previous page of newer messages. Treat '
                                                        'this value as an opaque cursor - do not parse, '
                                                        'validate, or assume any format for it. Ignored when '
                                                        '`after` is also set.\n'},
                              'channel': {'wire': 'channel',
                                          'in': 'query',
                                          'type': 'string',
                                          'required': False,
                                          'description': 'Filter by delivery channel.',
                                          'enum': ['sms',
                                                   'email',
                                                   'androidpush',
                                                   'iospush',
                                                   'webpush',
                                                   'inbox',
                                                   'whatsapp',
                                                   'slack',
                                                   'ms_teams']},
                              'recipient_ids_json': {'wire': 'recipient_id[]',
                                                     'in': 'query',
                                                     'type': 'array',
                                                     'required': False,
                                                     'description': 'Filter by one or more recipient '
                                                                    '`distinct_id`s (OR-ed). Repeat the '
                                                                    'param for each value, e.g. '
                                                                    '`?recipient_id[]=user_123&recipient_id[]=user_456`.'},
                              'categorys_json': {'wire': 'category[]',
                                                 'in': 'query',
                                                 'type': 'array',
                                                 'required': False,
                                                 'description': 'Filter by one or more notification '
                                                                'categories (OR-ed). Repeat the param for '
                                                                'each value, e.g. '
                                                                '`?category[]=transactional&category[]=promotional`.'},
                              'created_at_gte': {'wire': 'created_at_gte',
                                                 'in': 'query',
                                                 'type': 'string',
                                                 'required': False,
                                                 'description': 'RFC3339 timestamp lower bound (inclusive). '
                                                                'Compared against the `created_at` column '
                                                                'which has **second precision** - sub-second '
                                                                'components in the filter value are '
                                                                'effectively truncated. Example: '
                                                                '`2026-04-26T21:34:33Z`.\n'},
                              'created_at_lte': {'wire': 'created_at_lte',
                                                 'in': 'query',
                                                 'type': 'string',
                                                 'required': False,
                                                 'description': 'RFC3339 timestamp upper bound (inclusive). '
                                                                'Same second-precision caveat as '
                                                                '`created_at_gte`. Must be `>= '
                                                                'created_at_gte` when both are set.\n'},
                              'workflow_slug': {'wire': 'workflow_slug',
                                                'in': 'query',
                                                'type': 'string',
                                                'required': False,
                                                'description': 'Filter messages triggered from a specific '
                                                               'workflow.'},
                              'execution_id': {'wire': 'execution_id',
                                               'in': 'query',
                                               'type': 'string',
                                               'required': False,
                                               'description': 'Matches `wf_exec_id` or `broadcast_id`.'},
                              'idempotency_key': {'wire': 'idempotency_key',
                                                  'in': 'query',
                                                  'type': 'string',
                                                  'required': False,
                                                  'description': 'Filter by the idempotency key associated '
                                                                 'with the message at trigger time.'},
                              'message_id': {'wire': 'message_id',
                                             'in': 'query',
                                             'type': 'string',
                                             'required': False,
                                             'description': 'Exact match on message ID.'},
                              'tenant_id': {'wire': 'tenant_id',
                                            'in': 'query',
                                            'type': 'string',
                                            'required': False,
                                            'description': 'Filter messages belonging to a specific tenant.'},
                              'is_campaign': {'wire': 'is_campaign',
                                              'in': 'query',
                                              'type': 'boolean',
                                              'required': False,
                                              'description': 'Set `true` to return only messages sent as '
                                                             'part of a broadcast/campaign.'},
                              'include_content': {'wire': 'include_content',
                                                  'in': 'query',
                                                  'type': 'boolean',
                                                  'required': False,
                                                  'description': 'Set `true` to include the rendered message '
                                                                 'content in each result object. When '
                                                                 '`false` (default), the `content` key is '
                                                                 'omitted from the response to keep payloads '
                                                                 'lightweight.'}}}}
