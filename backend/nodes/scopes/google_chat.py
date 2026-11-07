"""Pinned Google Chat discovery operations and OAuth scope requirements."""

from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement

CATALOG = {'source': 'https://chat.googleapis.com/$discovery/rest?version=v1',
 'sha256': '2e22387d0c83790b0e875cc7cd88520f78ac3356f1aaafb7945520d2e150eec9',
 'scopes': ['https://www.googleapis.com/auth/chat.spaces',
            'https://www.googleapis.com/auth/chat.messages',
            'https://www.googleapis.com/auth/chat.memberships'],
 'operations': [{'name': 'list_spaces',
                 'label': 'List Spaces',
                 'category': 'Spaces',
                 'description': "Lists spaces the caller is a member of. Group chats and DMs aren't listed "
                                'until the first message is sent. For an example, see [List '
                                'spaces](https://developers.google.com/workspace/chat/list-spaces). Supports '
                                'the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [App '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app) '
                                'with the authorization scope: - `https://www.googleapis.com/auth/chat.bot` '
                                '- [User '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user) '
                                'wi',
                 'method': 'GET',
                 'path': 'v1/spaces',
                 'path_params': [],
                 'query_params': [{'name': 'pageToken',
                                   'required': False,
                                   'description': 'Optional. A page token, received from a previous list '
                                                  'spaces call. Provide this parameter to retrieve the '
                                                  'subsequent page. When paginating, the filter value should '
                                                  'match the call that provided the page token. Passing a '
                                                  'different value may lead to unexpected results.',
                                   'type': 'string'},
                                  {'name': 'filter',
                                   'required': False,
                                   'description': 'Optional. A query filter. You can filter spaces by the '
                                                  'space type '
                                                  '([`space_type`](https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces#spacetype)). '
                                                  'To filter by space type, you must specify valid enum '
                                                  'value, such as `SPACE` or `GROUP_CHAT` (the `space_type` '
                                                  "can't be `SPACE_TYPE_UNSPECIFIED`). To query for multiple "
                                                  'space types, ',
                                   'type': 'string'},
                                  {'name': 'pageSize',
                                   'required': False,
                                   'description': 'Optional. The maximum number of spaces to return. The '
                                                  'service might return fewer than this value. If '
                                                  'unspecified, at most 100 spaces are returned. The maximum '
                                                  "value is 1000. If you use a value more than 1000, it's "
                                                  'automatically changed to 1000. Negative values return an '
                                                  '`INVALID_ARGUMENT` error.',
                                   'type': 'integer'}],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.spaces'},
                {'name': 'spaces_create',
                 'label': 'Spaces Create',
                 'category': 'Spaces',
                 'description': 'Creates a space. Can be used to create a named space, or a group chat in '
                                '`Import mode`. For an example, see [Create a '
                                'space](https://developers.google.com/workspace/chat/create-spaces). '
                                'Supports the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [App '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app) '
                                'with [administrator approval](https://support.google.com/a?p=chat-app-auth) '
                                'and one of the following authorization scopes: - '
                                '`https://www.googleapis.com/auth/chat.app.spaces.create` - `https://w',
                 'method': 'POST',
                 'path': 'v1/spaces',
                 'path_params': [],
                 'query_params': [{'name': 'requestId',
                                   'required': False,
                                   'description': 'Optional. A unique ID for this request. A random UUID is '
                                                  'recommended. Specifying a request ID makes the request '
                                                  'idempotent, which ensures that multiple identical '
                                                  'requests with the same request ID result in only a single '
                                                  'space being created. Subsequent requests with the same '
                                                  'request ID return the existing space and do not update '
                                                  'the space, even if t',
                                   'type': 'string'}],
                 'body_json': True,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.spaces'},
                {'name': 'spaces_find_direct_message',
                 'label': 'Spaces Find Direct Message',
                 'category': 'Spaces',
                 'description': 'Returns the existing direct message with the specified user. If no direct '
                                'message space is found, returns a `404 NOT_FOUND` error. For an example, '
                                'see [Find a direct '
                                'message](/chat/api/guides/v1/spaces/find-direct-message). With [app '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app), '
                                'returns the direct message space between the specified user and the calling '
                                'Chat app. With [user '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user), '
                                'returns the direct message space between the specified user and the '
                                'authentica',
                 'method': 'GET',
                 'path': 'v1/spaces:findDirectMessage',
                 'path_params': [],
                 'query_params': [{'name': 'name',
                                   'required': False,
                                   'description': 'Required. Resource name of the user to find direct '
                                                  'message with. Format: `users/{user}`, where `{user}` is '
                                                  'either the `id` for the '
                                                  '[person](https://developers.google.com/people/api/rest/v1/people) '
                                                  'from the People API, or the `id` for the '
                                                  '[user](https://developers.google.com/admin-sdk/directory/reference/rest/v1/users) '
                                                  'in the Directory API. For exam',
                                   'type': 'string'}],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.spaces'},
                {'name': 'spaces_find_group_chats',
                 'label': 'Spaces Find Group Chats',
                 'category': 'Spaces',
                 'description': 'Returns all spaces with `spaceType == GROUP_CHAT`, whose human memberships '
                                'contain exactly the calling user, and the users specified in '
                                '`FindGroupChatsRequest.users`. Only members that have joined the '
                                'conversation are supported. For an example, see [Find group '
                                'chats](https://developers.google.com/workspace/chat/find-group-chats). If '
                                'the calling user blocks, or is blocked by, some users, and no spaces with '
                                'the entire specified set of users are found, this method returns spaces '
                                "that don't include the blocked or blocking users. The specified set of "
                                'users must contain only human (non-app) membersh',
                 'method': 'GET',
                 'path': 'v1/spaces:findGroupChats',
                 'path_params': [],
                 'query_params': [{'name': 'pageToken',
                                   'required': False,
                                   'description': 'Optional. A page token, received from a previous call to '
                                                  'find group chats. Provide this parameter to retrieve the '
                                                  'subsequent page. When paginating, all other parameters '
                                                  'provided should match the call that provided the token. '
                                                  'Passing different values may lead to unexpected results.',
                                   'type': 'string'},
                                  {'name': 'pageSize',
                                   'required': False,
                                   'description': 'Optional. The maximum number of spaces to return. The '
                                                  'service might return fewer than this value. If '
                                                  'unspecified, at most 10 spaces are returned. The maximum '
                                                  "value is 30. If you use a value more than 30, it's "
                                                  'automatically changed to 30. Negative values return an '
                                                  '`INVALID_ARGUMENT` error.',
                                   'type': 'integer'},
                                  {'name': 'spaceView',
                                   'required': False,
                                   'description': 'Requested space view type. If unset, defaults to '
                                                  '`SPACE_VIEW_RESOURCE_NAME_ONLY`. Requests that specify '
                                                  '`SPACE_VIEW_EXPANDED` must include scopes that allow '
                                                  'reading space data, for example, '
                                                  'https://www.googleapis.com/auth/chat.spaces or '
                                                  'https://www.googleapis.com/auth/chat.spaces.readonly.',
                                   'type': 'string'},
                                  {'name': 'users',
                                   'required': False,
                                   'description': 'Optional. Resource names of all human users in group chat '
                                                  "with the calling user. Chat apps can't be included in the "
                                                  'request. The maximum number of users that can be '
                                                  'specified in a single request is `49`. Format: '
                                                  '`users/{user}`, where `{user}` is either the `id` for the '
                                                  '[person](https://developers.google.com/people/api/rest/v1/people) '
                                                  'from the Peopl',
                                   'type': 'string'}],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.memberships'},
                {'name': 'spaces_get',
                 'label': 'Spaces Get',
                 'category': 'Spaces',
                 'description': 'Returns details about a space. For an example, see [Get details about a '
                                'space](https://developers.google.com/workspace/chat/get-spaces). Supports '
                                'the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [App '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app) '
                                'with one of the following authorization scopes: - '
                                '`https://www.googleapis.com/auth/chat.bot` - '
                                '`https://www.googleapis.com/auth/chat.app.spaces` with [administrator '
                                'approval](https://support.google.com/a?p=chat-app-auth) - [User '
                                'authentication',
                 'method': 'GET',
                 'path': 'v1/{+name}',
                 'path_params': [{'name': 'name',
                                  'required': True,
                                  'description': 'Required. Resource name of the space, in the form '
                                                 '`spaces/{space}`. Format: `spaces/{space}`',
                                  'type': 'string'}],
                 'query_params': [{'name': 'useAdminAccess',
                                   'required': False,
                                   'description': "Optional. When `true`, the method runs using the user's "
                                                  'Google Workspace administrator privileges. The calling '
                                                  'user must be a Google Workspace administrator with the '
                                                  '[manage chat and spaces conversations '
                                                  'privilege](https://support.google.com/a/answer/13369245). '
                                                  'Requires the `chat.admin.spaces` or '
                                                  '`chat.admin.spaces.readonly` [OAuth 2.0 scopes](http',
                                   'type': 'boolean'}],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.spaces'},
                {'name': 'spaces_members_create',
                 'label': 'Spaces Members Create',
                 'category': 'Spaces',
                 'description': 'Creates a membership for the calling Chat app, a user, or a Google Group. '
                                "Creating memberships for other Chat apps isn't supported. When creating a "
                                'membership, if the specified member has their auto-accept policy turned '
                                "off, then they're invited, and must accept the space invitation before "
                                'joining. Otherwise, creating a membership adds the member directly to the '
                                'specified space. Supports the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [App '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app',
                 'method': 'POST',
                 'path': 'v1/{+parent}/members',
                 'path_params': [{'name': 'parent',
                                  'required': True,
                                  'description': 'Required. The resource name of the space for which to '
                                                 'create the membership. Format: spaces/{space}',
                                  'type': 'string'}],
                 'query_params': [{'name': 'useAdminAccess',
                                   'required': False,
                                   'description': "Optional. When `true`, the method runs using the user's "
                                                  'Google Workspace administrator privileges. The calling '
                                                  'user must be a Google Workspace administrator with the '
                                                  '[manage chat and spaces conversations '
                                                  'privilege](https://support.google.com/a/answer/13369245). '
                                                  'Requires the `chat.admin.memberships` [OAuth 2.0 '
                                                  'scope](https://developers.google.com/wo',
                                   'type': 'boolean'}],
                 'body_json': True,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.memberships'},
                {'name': 'spaces_members_delete',
                 'label': 'Spaces Members Delete',
                 'category': 'Spaces',
                 'description': 'Deletes a membership. For an example, see [Remove a user or a Google Chat '
                                'app from a '
                                'space](https://developers.google.com/workspace/chat/delete-members). '
                                'Supports the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [App '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app) '
                                'with [administrator approval](https://support.google.com/a?p=chat-app-auth) '
                                'and the authorization scope: - '
                                '`https://www.googleapis.com/auth/chat.app.memberships` - [User '
                                'authentication](https://developers.google.com/workspace/',
                 'method': 'DELETE',
                 'path': 'v1/{+name}',
                 'path_params': [{'name': 'name',
                                  'required': True,
                                  'description': 'Required. Resource name of the membership to delete. Chat '
                                                 "apps can delete human users' or their own memberships. "
                                                 "Chat apps can't delete other apps' memberships. When "
                                                 'deleting a human membership, requires the '
                                                 '`chat.memberships` scope with [user '
                                                 'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user) '
                                                 'or the `cha',
                                  'type': 'string'}],
                 'query_params': [{'name': 'useAdminAccess',
                                   'required': False,
                                   'description': "Optional. When `true`, the method runs using the user's "
                                                  'Google Workspace administrator privileges. The calling '
                                                  'user must be a Google Workspace administrator with the '
                                                  '[manage chat and spaces conversations '
                                                  'privilege](https://support.google.com/a/answer/13369245). '
                                                  'Requires the `chat.admin.memberships` [OAuth 2.0 '
                                                  'scope](https://developers.google.com/wo',
                                   'type': 'boolean'}],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.memberships'},
                {'name': 'spaces_members_get',
                 'label': 'Spaces Members Get',
                 'category': 'Spaces',
                 'description': 'Returns details about a membership. For an example, see [Get details about '
                                "a user's or Google Chat app's "
                                'membership](https://developers.google.com/workspace/chat/get-members). '
                                'Supports the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [App '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app) '
                                'with one of the following authorization scopes: - '
                                '`https://www.googleapis.com/auth/chat.bot` - '
                                '`https://www.googleapis.com/auth/chat.app.memberships` (requires '
                                '[administrator approval](https://support.goo',
                 'method': 'GET',
                 'path': 'v1/{+name}',
                 'path_params': [{'name': 'name',
                                  'required': True,
                                  'description': 'Required. Resource name of the membership to retrieve. To '
                                                 "get the app's own membership [by using user "
                                                 'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user), '
                                                 'you can optionally use `spaces/{space}/members/app`. '
                                                 'Format: `spaces/{space}/members/{member}` or '
                                                 "`spaces/{space}/members/app` You can use the user's em",
                                  'type': 'string'}],
                 'query_params': [{'name': 'useAdminAccess',
                                   'required': False,
                                   'description': "Optional. When `true`, the method runs using the user's "
                                                  'Google Workspace administrator privileges. The calling '
                                                  'user must be a Google Workspace administrator with the '
                                                  '[manage chat and spaces conversations '
                                                  'privilege](https://support.google.com/a/answer/13369245). '
                                                  'Requires the `chat.admin.memberships` or '
                                                  '`chat.admin.memberships.readonly` [OAuth 2.0 sc',
                                   'type': 'boolean'}],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.memberships'},
                {'name': 'spaces_members_list',
                 'label': 'Spaces Members List',
                 'category': 'Spaces',
                 'description': 'Lists memberships in a space. For an example, see [List users and Google '
                                'Chat apps in a '
                                'space](https://developers.google.com/workspace/chat/list-members). Listing '
                                'memberships with [app '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app) '
                                'lists memberships in spaces that the Chat app has access to, but excludes '
                                'Chat app memberships, including its own. Listing memberships with [User '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user) '
                                'lists memberships in spaces that the authenticated user has access to. '
                                'Supports ',
                 'method': 'GET',
                 'path': 'v1/{+parent}/members',
                 'path_params': [{'name': 'parent',
                                  'required': True,
                                  'description': 'Required. The resource name of the space for which to '
                                                 'fetch a membership list. Format: spaces/{space}',
                                  'type': 'string'}],
                 'query_params': [{'name': 'showInvited',
                                   'required': False,
                                   'description': 'Optional. When `true`, also returns memberships '
                                                  'associated with invited members, in addition to other '
                                                  'types of memberships. If a filter is set, invited '
                                                  "memberships that don't match the filter criteria aren't "
                                                  'returned. Currently requires [user '
                                                  'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user).',
                                   'type': 'boolean'},
                                  {'name': 'showGroups',
                                   'required': False,
                                   'description': 'Optional. When `true`, also returns memberships '
                                                  'associated with a Google Group, in addition to other '
                                                  'types of memberships. If a filter is set, Google Group '
                                                  "memberships that don't match the filter criteria aren't "
                                                  'returned.',
                                   'type': 'boolean'},
                                  {'name': 'useAdminAccess',
                                   'required': False,
                                   'description': "Optional. When `true`, the method runs using the user's "
                                                  'Google Workspace administrator privileges. The calling '
                                                  'user must be a Google Workspace administrator with the '
                                                  '[manage chat and spaces conversations '
                                                  'privilege](https://support.google.com/a/answer/13369245). '
                                                  'Requires either the `chat.admin.memberships.readonly` or '
                                                  '`chat.admin.memberships` [OAuth',
                                   'type': 'boolean'},
                                  {'name': 'pageToken',
                                   'required': False,
                                   'description': 'Optional. A page token, received from a previous call to '
                                                  'list memberships. Provide this parameter to retrieve the '
                                                  'subsequent page. When paginating, all other parameters '
                                                  'provided should match the call that provided the page '
                                                  'token. Passing different values to the other parameters '
                                                  'might lead to unexpected results.',
                                   'type': 'string'},
                                  {'name': 'pageSize',
                                   'required': False,
                                   'description': 'Optional. The maximum number of memberships to return. '
                                                  'The service might return fewer than this value. If '
                                                  'unspecified, at most 100 memberships are returned. The '
                                                  'maximum value is 1000. If you use a value more than 1000, '
                                                  "it's automatically changed to 1000. Negative values "
                                                  'return an `INVALID_ARGUMENT` error.',
                                   'type': 'integer'},
                                  {'name': 'filter',
                                   'required': False,
                                   'description': 'Optional. A query filter. You can filter memberships by a '
                                                  "member's role "
                                                  '([`role`](https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces.members#membershiprole)) '
                                                  'and type '
                                                  '([`member.type`](https://developers.google.com/workspace/chat/api/reference/rest/v1/User#type)). '
                                                  'To filter by role, set `role` to `ROLE_MEMBER` or '
                                                  '`ROLE_MANAGER',
                                   'type': 'string'}],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.memberships'},
                {'name': 'spaces_members_patch',
                 'label': 'Spaces Members Patch',
                 'category': 'Spaces',
                 'description': "Updates a membership. For an example, see [Update a user's membership in a "
                                'space](https://developers.google.com/workspace/chat/update-members). '
                                'Supports the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [App '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app) '
                                'with [administrator approval](https://support.google.com/a?p=chat-app-auth) '
                                'and the authorization scope: - '
                                '`https://www.googleapis.com/auth/chat.app.memberships` (only in spaces the '
                                'app created) - [User authentication](https://developer',
                 'method': 'PATCH',
                 'path': 'v1/{+name}',
                 'path_params': [{'name': 'name',
                                  'required': True,
                                  'description': 'Identifier. Resource name of the membership, assigned by '
                                                 'the server. Format: `spaces/{space}/members/{member}`',
                                  'type': 'string'}],
                 'query_params': [{'name': 'updateMask',
                                   'required': False,
                                   'description': 'Required. The field paths to update. Separate multiple '
                                                  'values with commas or use `*` to update all field paths. '
                                                  'Currently supported field paths: - `role`',
                                   'type': 'string'},
                                  {'name': 'useAdminAccess',
                                   'required': False,
                                   'description': "Optional. When `true`, the method runs using the user's "
                                                  'Google Workspace administrator privileges. The calling '
                                                  'user must be a Google Workspace administrator with the '
                                                  '[manage chat and spaces conversations '
                                                  'privilege](https://support.google.com/a/answer/13369245). '
                                                  'Requires the `chat.admin.memberships` [OAuth 2.0 '
                                                  'scope](https://developers.google.com/wo',
                                   'type': 'boolean'}],
                 'body_json': True,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.memberships'},
                {'name': 'spaces_message_pins_create',
                 'label': 'Spaces Message Pins Create',
                 'category': 'Spaces',
                 'description': 'Creates a message pin. Requires [user '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user) '
                                'with one of the following [authorization '
                                'scopes](https://developers.google.com/workspace/chat/authenticate-authorize#chat-api-scopes): '
                                '- `https://www.googleapis.com/auth/chat.spaces.pins` - '
                                '`https://www.googleapis.com/auth/chat.spaces`',
                 'method': 'POST',
                 'path': 'v1/{+parent}/messagePins',
                 'path_params': [{'name': 'parent',
                                  'required': True,
                                  'description': 'Required. The parent space in which to create the message '
                                                 'pin. Format: spaces/{space}',
                                  'type': 'string'}],
                 'query_params': [],
                 'body_json': True,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.spaces'},
                {'name': 'spaces_message_pins_delete',
                 'label': 'Spaces Message Pins Delete',
                 'category': 'Spaces',
                 'description': 'Deletes a message pin. Requires [user '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user) '
                                'with one of the following [authorization '
                                'scopes](https://developers.google.com/workspace/chat/authenticate-authorize#chat-api-scopes): '
                                '- `https://www.googleapis.com/auth/chat.spaces.pins` - '
                                '`https://www.googleapis.com/auth/chat.spaces`',
                 'method': 'DELETE',
                 'path': 'v1/{+name}',
                 'path_params': [{'name': 'name',
                                  'required': True,
                                  'description': 'Required. The resource name of the message pin to remove. '
                                                 'Format: spaces/{space}/messagePins/{message_pin}',
                                  'type': 'string'}],
                 'query_params': [],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.spaces'},
                {'name': 'spaces_message_pins_list',
                 'label': 'Spaces Message Pins List',
                 'category': 'Spaces',
                 'description': 'Lists message pins in a space. Users can pin important messages in spaces '
                                'for easy access. For more information, see [Pin or unpin a conversation in '
                                'Google Chat](https://support.google.com/chat/answer/15622437). Requires '
                                '[user '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user) '
                                'with one of the following [authorization '
                                'scopes](https://developers.google.com/workspace/chat/authenticate-authorize#chat-api-scopes): '
                                '- `https://www.googleapis.com/auth/chat.spaces.pins.readonly` - '
                                '`https://www.googleapis.com/auth/chat.spaces.pins` - '
                                '`https://www.googleapis.co',
                 'method': 'GET',
                 'path': 'v1/{+parent}/messagePins',
                 'path_params': [{'name': 'parent',
                                  'required': True,
                                  'description': 'Required. The parent space which owns the collection of '
                                                 'pinned items Format: `spaces/{space}`',
                                  'type': 'string'}],
                 'query_params': [{'name': 'pageSize',
                                   'required': False,
                                   'description': 'Optional. The maximum number of message pins returned. '
                                                  'The service might return fewer messages than this value. '
                                                  'The maximum value is 100. If you use a value more than '
                                                  "100, it's automatically changed to 100. If unspecified, "
                                                  'at most 100 message pins will be returned. Negative '
                                                  'values return an `INVALID_ARGUMENT` error.',
                                   'type': 'integer'},
                                  {'name': 'pageToken',
                                   'required': False,
                                   'description': 'Optional. A page token received from a previous list '
                                                  'message pins call. Provide this parameter to retrieve the '
                                                  'subsequent page. When paginating, all other parameters '
                                                  'provided should match the call that provided the page '
                                                  'token. Passing different values to the other parameters '
                                                  'might lead to unexpected results.',
                                   'type': 'string'}],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.spaces'},
                {'name': 'spaces_messages_create',
                 'label': 'Spaces Messages Create',
                 'category': 'Spaces',
                 'description': 'Creates a message in a Google Chat space. For an example, see [Send a '
                                'message](https://developers.google.com/workspace/chat/create-messages). '
                                'Supports the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [App '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app) '
                                'with the authorization scope: - `https://www.googleapis.com/auth/chat.bot` '
                                '- [User '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user) '
                                'with one of the following authorization scopes: - `https://w',
                 'method': 'POST',
                 'path': 'v1/{+parent}/messages',
                 'path_params': [{'name': 'parent',
                                  'required': True,
                                  'description': 'Required. The resource name of the space in which to '
                                                 'create a message. Format: `spaces/{space}`',
                                  'type': 'string'}],
                 'query_params': [{'name': 'createMessageNotificationOptions.notificationType',
                                   'required': False,
                                   'description': 'The notification type for the message.',
                                   'type': 'string'},
                                  {'name': 'requestId',
                                   'required': False,
                                   'description': 'Optional. A unique ID for this request. A random UUID is '
                                                  'recommended. Specifying a request ID makes the request '
                                                  'idempotent, which ensures that multiple identical '
                                                  'requests with the same request ID result in only a single '
                                                  'message being created. Subsequent requests with the same '
                                                  'request ID return the existing message and do not update '
                                                  'the message, eve',
                                   'type': 'string'},
                                  {'name': 'threadKey',
                                   'required': False,
                                   'description': 'Optional. Deprecated: Use thread.thread_key instead. ID '
                                                  'for the thread. Supports up to 4000 characters. To start '
                                                  'or add to a thread, create a message and specify a '
                                                  '`threadKey` or the thread.name. For example usage, see '
                                                  '[Start or reply to a message '
                                                  'thread](https://developers.google.com/workspace/chat/create-messages#create-message-thread).',
                                   'type': 'string'},
                                  {'name': 'messageId',
                                   'required': False,
                                   'description': 'Optional. A custom ID for a message. Lets Chat apps get, '
                                                  'update, or delete a message without needing to store the '
                                                  "system-assigned ID in the message's resource name "
                                                  '(represented in the message `name` field). The value for '
                                                  'this field must meet the following requirements: * Begins '
                                                  'with `client-`. For example, `client-custom-name` is a '
                                                  'valid custom ID,',
                                   'type': 'string'},
                                  {'name': 'messageReplyOption',
                                   'required': False,
                                   'description': 'Optional. Specifies whether a message starts a thread or '
                                                  'replies to one. Only supported in named spaces. When '
                                                  '[responding to user '
                                                  'interactions](https://developers.google.com/workspace/chat/receive-respond-interactions), '
                                                  'this field is ignored. For interactions within a thread, '
                                                  'the reply is created in the same thread. Otherwise, the '
                                                  'reply is created ',
                                   'type': 'string'}],
                 'body_json': True,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.messages'},
                {'name': 'spaces_messages_delete',
                 'label': 'Spaces Messages Delete',
                 'category': 'Spaces',
                 'description': 'Deletes a message. For an example, see [Delete a '
                                'message](https://developers.google.com/workspace/chat/delete-messages). '
                                'Supports the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [App '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app) '
                                'with the authorization scope: - `https://www.googleapis.com/auth/chat.bot` '
                                '- [User '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user) '
                                'with one of the following authorization scopes: - '
                                '`https://www.googleapis.com/aut',
                 'method': 'DELETE',
                 'path': 'v1/{+name}',
                 'path_params': [{'name': 'name',
                                  'required': True,
                                  'description': 'Required. Resource name of the message. Format: '
                                                 "`spaces/{space}/messages/{message}` If you've set a custom "
                                                 'ID for your message, you can use the value from the '
                                                 '`clientAssignedMessageId` field for `{message}`. For '
                                                 'details, see [Name a message] '
                                                 '(https://developers.google.com/workspace/chat/create-messages#name_a_created_message).',
                                  'type': 'string'}],
                 'query_params': [{'name': 'force',
                                   'required': False,
                                   'description': 'Optional. When `true`, deleting a message also deletes '
                                                  'its threaded replies. When `false`, if a message has '
                                                  'threaded replies, deletion fails. Only applies when '
                                                  '[authenticating as a '
                                                  'user](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user). '
                                                  'Has no effect when [authenticating as a Chat app] '
                                                  '(https://developers.google.com/wo',
                                   'type': 'boolean'}],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.messages'},
                {'name': 'spaces_messages_get',
                 'label': 'Spaces Messages Get',
                 'category': 'Spaces',
                 'description': 'Returns details about a message. For an example, see [Get details about a '
                                'message](https://developers.google.com/workspace/chat/get-messages). '
                                'Supports the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [App '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app) '
                                'with one of the following authorization scopes: - '
                                '`https://www.googleapis.com/auth/chat.bot`: When using this authorization '
                                'scope, this method returns details about a message the Chat app has access '
                                'to, like direct messages and [slash co',
                 'method': 'GET',
                 'path': 'v1/{+name}',
                 'path_params': [{'name': 'name',
                                  'required': True,
                                  'description': 'Required. Resource name of the message. Format: '
                                                 "`spaces/{space}/messages/{message}` If you've set a custom "
                                                 'ID for your message, you can use the value from the '
                                                 '`clientAssignedMessageId` field for `{message}`. For '
                                                 'details, see [Name a message] '
                                                 '(https://developers.google.com/workspace/chat/create-messages#name_a_created_message).',
                                  'type': 'string'}],
                 'query_params': [{'name': 'markupSyntax',
                                   'required': False,
                                   'description': 'Optional. Specifies the desired output syntax for the '
                                                  'Chat message `formatted_text` field.',
                                   'type': 'string'}],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.messages'},
                {'name': 'spaces_messages_list',
                 'label': 'Spaces Messages List',
                 'category': 'Spaces',
                 'description': 'Lists messages in a space that the caller is a member of, including '
                                'messages from blocked members and spaces. System messages, like those '
                                "announcing new space members, aren't included. If you list messages from a "
                                'space with no messages, the response is an empty object. When using a '
                                'REST/HTTP interface, the response contains an empty JSON object, `{}`. For '
                                'an example, see [List '
                                'messages](https://developers.google.com/workspace/chat/api/guides/v1/messages/list). '
                                'Supports the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [App authentic',
                 'method': 'GET',
                 'path': 'v1/{+parent}/messages',
                 'path_params': [{'name': 'parent',
                                  'required': True,
                                  'description': 'Required. The resource name of the space to list messages '
                                                 'from. Format: `spaces/{space}`',
                                  'type': 'string'}],
                 'query_params': [{'name': 'markupSyntax',
                                   'required': False,
                                   'description': 'Optional. Specifies the desired output syntax for the '
                                                  'Chat message `formatted_text` field.',
                                   'type': 'string'},
                                  {'name': 'filter',
                                   'required': False,
                                   'description': 'Optional. A query filter. You can filter messages by date '
                                                  '(`create_time`) and thread (`thread.name`). To filter '
                                                  'messages by the date they were created, specify the '
                                                  '`create_time` with a timestamp in '
                                                  '[RFC-3339](https://www.rfc-editor.org/rfc/rfc3339) format '
                                                  'and double quotation marks. For example, '
                                                  '`"2023-04-21T11:30:00-04:00"`. You can use the greate',
                                   'type': 'string'},
                                  {'name': 'orderBy',
                                   'required': False,
                                   'description': 'Optional. How the list of messages is ordered. Specify a '
                                                  'value to order by an ordering operation. Valid ordering '
                                                  'operation values are as follows: - `ASC` for ascending. - '
                                                  '`DESC` for descending. The default ordering is '
                                                  '`create_time ASC`.',
                                   'type': 'string'},
                                  {'name': 'showDeleted',
                                   'required': False,
                                   'description': 'Optional. Whether to include deleted messages. Deleted '
                                                  'messages include deleted time and metadata about their '
                                                  'deletion, but message content is unavailable.',
                                   'type': 'boolean'},
                                  {'name': 'pageToken',
                                   'required': False,
                                   'description': 'Optional. A page token received from a previous list '
                                                  'messages call. Provide this parameter to retrieve the '
                                                  'subsequent page. When paginating, all other parameters '
                                                  'provided should match the call that provided the page '
                                                  'token. Passing different values to the other parameters '
                                                  'might lead to unexpected results.',
                                   'type': 'string'},
                                  {'name': 'pageSize',
                                   'required': False,
                                   'description': 'Optional. The maximum number of messages returned. The '
                                                  'service might return fewer messages than this value. If '
                                                  'unspecified, at most 25 are returned. The maximum value '
                                                  "is 1000. If you use a value more than 1000, it's "
                                                  'automatically changed to 1000. Negative values return an '
                                                  '`INVALID_ARGUMENT` error.',
                                   'type': 'integer'}],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.messages'},
                {'name': 'spaces_messages_patch',
                 'label': 'Spaces Messages Patch',
                 'category': 'Spaces',
                 'description': "Updates a message. There's a difference between the `patch` and `update` "
                                'methods. The `patch` method uses a `patch` request while the `update` '
                                'method uses a `put` request. We recommend using the `patch` method. For an '
                                'example, see [Update a '
                                'message](https://developers.google.com/workspace/chat/update-messages). '
                                'Supports the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [App '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app) '
                                'with the authorization scope: - `https://www.googleapis.com/auth/ch',
                 'method': 'PATCH',
                 'path': 'v1/{+name}',
                 'path_params': [{'name': 'name',
                                  'required': True,
                                  'description': 'Identifier. Resource name of the message. Format: '
                                                 '`spaces/{space}/messages/{message}` Where `{space}` is the '
                                                 'ID of the space where the message is posted and '
                                                 '`{message}` is a system-assigned ID for the message. For '
                                                 'example, '
                                                 '`spaces/AAAAAAAAAAA/messages/BBBBBBBBBBB.BBBBBBBBBBB`. If '
                                                 'you set a custom ID when you create a message, you can use '
                                                 'this ID to',
                                  'type': 'string'}],
                 'query_params': [{'name': 'allowMissing',
                                   'required': False,
                                   'description': "Optional. If `true` and the message isn't found, a new "
                                                  'message is created and `updateMask` is ignored. The '
                                                  'specified message ID must be '
                                                  '[client-assigned](https://developers.google.com/workspace/chat/create-messages#name_a_created_message) '
                                                  'or the request fails.',
                                   'type': 'boolean'},
                                  {'name': 'updateMask',
                                   'required': False,
                                   'description': 'Required. The field paths to update. Separate multiple '
                                                  'values with commas or use `*` to update all field paths. '
                                                  'Currently supported field paths: - `text` - `attachment` '
                                                  '- `cards` (Requires [app '
                                                  'authentication](/chat/api/guides/auth/service-accounts).) '
                                                  '- `cards_v2` (Requires [app '
                                                  'authentication](/chat/api/guides/auth/service-accounts).) '
                                                  '- `accessory',
                                   'type': 'string'}],
                 'body_json': True,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.messages'},
                {'name': 'spaces_messages_reactions_create',
                 'label': 'Spaces Messages Reactions Create',
                 'category': 'Spaces',
                 'description': 'Creates a reaction and adds it to a message. For an example, see [Add a '
                                'reaction to a '
                                'message](https://developers.google.com/workspace/chat/create-reactions). '
                                'Requires [user '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user) '
                                'with one of the following [authorization '
                                'scopes](https://developers.google.com/workspace/chat/authenticate-authorize#chat-api-scopes): '
                                '- `https://www.googleapis.com/auth/chat.messages.reactions.create` - '
                                '`https://www.googleapis.com/auth/chat.messages.reactions` - '
                                '`https://www.googleapis.com/auth/chat.messages` - `https://www.goog',
                 'method': 'POST',
                 'path': 'v1/{+parent}/reactions',
                 'path_params': [{'name': 'parent',
                                  'required': True,
                                  'description': 'Required. The message where the reaction is created. '
                                                 'Format: `spaces/{space}/messages/{message}`',
                                  'type': 'string'}],
                 'query_params': [],
                 'body_json': True,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.messages'},
                {'name': 'spaces_messages_reactions_delete',
                 'label': 'Spaces Messages Reactions Delete',
                 'category': 'Spaces',
                 'description': 'Deletes a reaction to a message. For an example, see [Delete a '
                                'reaction](https://developers.google.com/workspace/chat/delete-reactions). '
                                'Requires [user '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user) '
                                'with one of the following [authorization '
                                'scopes](https://developers.google.com/workspace/chat/authenticate-authorize#chat-api-scopes): '
                                '- `https://www.googleapis.com/auth/chat.messages.reactions` - '
                                '`https://www.googleapis.com/auth/chat.messages` - '
                                '`https://www.googleapis.com/auth/chat.import` (import mode spaces only)',
                 'method': 'DELETE',
                 'path': 'v1/{+name}',
                 'path_params': [{'name': 'name',
                                  'required': True,
                                  'description': 'Required. Name of the reaction to delete. Format: '
                                                 '`spaces/{space}/messages/{message}/reactions/{reaction}`',
                                  'type': 'string'}],
                 'query_params': [],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.messages'},
                {'name': 'spaces_messages_reactions_list',
                 'label': 'Spaces Messages Reactions List',
                 'category': 'Spaces',
                 'description': 'Lists reactions to a message. For an example, see [List reactions for a '
                                'message](https://developers.google.com/workspace/chat/list-reactions). '
                                'Requires [user '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user) '
                                'with one of the following [authorization '
                                'scopes](https://developers.google.com/workspace/chat/authenticate-authorize#chat-api-scopes): '
                                '- `https://www.googleapis.com/auth/chat.messages.reactions.readonly` - '
                                '`https://www.googleapis.com/auth/chat.messages.reactions` - '
                                '`https://www.googleapis.com/auth/chat.messages.readonly` - '
                                '`https://www.googleapi',
                 'method': 'GET',
                 'path': 'v1/{+parent}/reactions',
                 'path_params': [{'name': 'parent',
                                  'required': True,
                                  'description': 'Required. The message users reacted to. Format: '
                                                 '`spaces/{space}/messages/{message}`',
                                  'type': 'string'}],
                 'query_params': [{'name': 'pageSize',
                                   'required': False,
                                   'description': 'Optional. The maximum number of reactions returned. The '
                                                  'service can return fewer reactions than this value. If '
                                                  'unspecified, the default value is 25. The maximum value '
                                                  'is 200; values above 200 are changed to 200.',
                                   'type': 'integer'},
                                  {'name': 'pageToken',
                                   'required': False,
                                   'description': 'Optional. (If resuming from a previous query.) A page '
                                                  'token received from a previous list reactions call. '
                                                  'Provide this to retrieve the subsequent page. When '
                                                  'paginating, the filter value should match the call that '
                                                  'provided the page token. Passing a different value might '
                                                  'lead to unexpected results.',
                                   'type': 'string'},
                                  {'name': 'filter',
                                   'required': False,
                                   'description': 'Optional. A query filter. You can filter reactions by '
                                                  '[emoji](https://developers.google.com/workspace/chat/api/reference/rest/v1/Emoji) '
                                                  '(either `emoji.unicode` or `emoji.custom_emoji.uid`) and '
                                                  '[user](https://developers.google.com/workspace/chat/api/reference/rest/v1/User) '
                                                  '(`user.name`). To filter reactions for multiple emojis or '
                                                  'users, join similar',
                                   'type': 'string'}],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.messages'},
                {'name': 'spaces_messages_search',
                 'label': 'Spaces Messages Search',
                 'category': 'Spaces',
                 'description': 'Searches for messages in Google Chat that the calling user has access to. '
                                'Returns a list of messages matching the search criteria. To search across '
                                'all spaces the user has access to, set `parent` to `spaces/-`. Using any '
                                'other value for `parent` results in an `INVALID_ARGUMENT` error. The '
                                'returned messages have their `name` field populated with the full resource '
                                'name, which includes the specific `space` in which the message resides. '
                                "This API doesn't return all message types. The types of messages listed "
                                "below aren't included in the response. Use ListMessages to list all "
                                'messages. - Private Mes',
                 'method': 'POST',
                 'path': 'v1/{+parent}/messages:search',
                 'path_params': [{'name': 'parent',
                                  'required': True,
                                  'description': 'Required. The resource name of the space to search within. '
                                                 'To search across all spaces the user has access to, set '
                                                 'this field to `spaces/-`. Using any other value for '
                                                 '`parent` results in an `INVALID_ARGUMENT` error. To limit '
                                                 'the search to one or more spaces, use `space.name` or '
                                                 '`space.display_name` in the `filter`.',
                                  'type': 'string'}],
                 'query_params': [],
                 'body_json': True,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.messages'},
                {'name': 'spaces_messages_update',
                 'label': 'Spaces Messages Update',
                 'category': 'Spaces',
                 'description': "Updates a message. There's a difference between the `patch` and `update` "
                                'methods. The `patch` method uses a `patch` request while the `update` '
                                'method uses a `put` request. We recommend using the `patch` method. For an '
                                'example, see [Update a '
                                'message](https://developers.google.com/workspace/chat/update-messages). '
                                'Supports the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [App '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app) '
                                'with the authorization scope: - `https://www.googleapis.com/auth/ch',
                 'method': 'PUT',
                 'path': 'v1/{+name}',
                 'path_params': [{'name': 'name',
                                  'required': True,
                                  'description': 'Identifier. Resource name of the message. Format: '
                                                 '`spaces/{space}/messages/{message}` Where `{space}` is the '
                                                 'ID of the space where the message is posted and '
                                                 '`{message}` is a system-assigned ID for the message. For '
                                                 'example, '
                                                 '`spaces/AAAAAAAAAAA/messages/BBBBBBBBBBB.BBBBBBBBBBB`. If '
                                                 'you set a custom ID when you create a message, you can use '
                                                 'this ID to',
                                  'type': 'string'}],
                 'query_params': [{'name': 'allowMissing',
                                   'required': False,
                                   'description': "Optional. If `true` and the message isn't found, a new "
                                                  'message is created and `updateMask` is ignored. The '
                                                  'specified message ID must be '
                                                  '[client-assigned](https://developers.google.com/workspace/chat/create-messages#name_a_created_message) '
                                                  'or the request fails.',
                                   'type': 'boolean'},
                                  {'name': 'updateMask',
                                   'required': False,
                                   'description': 'Required. The field paths to update. Separate multiple '
                                                  'values with commas or use `*` to update all field paths. '
                                                  'Currently supported field paths: - `text` - `attachment` '
                                                  '- `cards` (Requires [app '
                                                  'authentication](/chat/api/guides/auth/service-accounts).) '
                                                  '- `cards_v2` (Requires [app '
                                                  'authentication](/chat/api/guides/auth/service-accounts).) '
                                                  '- `accessory',
                                   'type': 'string'}],
                 'body_json': True,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.messages'},
                {'name': 'spaces_patch',
                 'label': 'Spaces Patch',
                 'category': 'Spaces',
                 'description': 'Updates a space. For an example, see [Update a '
                                'space](https://developers.google.com/workspace/chat/update-spaces). If '
                                "you're updating the `displayName` field and receive the error message "
                                '`ALREADY_EXISTS`, try a different display name.. An existing space within '
                                'the Google Workspace organization might already use this display name. '
                                'Supports the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [App '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-app) '
                                'with [administrator approval](https://support.g',
                 'method': 'PATCH',
                 'path': 'v1/{+name}',
                 'path_params': [{'name': 'name',
                                  'required': True,
                                  'description': 'Identifier. Resource name of the space. Format: '
                                                 '`spaces/{space}` Where `{space}` represents the '
                                                 'system-assigned ID for the space. You can obtain the space '
                                                 'ID by calling the '
                                                 '[`spaces.list()`](https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces/list) '
                                                 'method or from the space URL. For example, if the space '
                                                 'URL is `https://mail.go',
                                  'type': 'string'}],
                 'query_params': [{'name': 'updateMask',
                                   'required': False,
                                   'description': 'Required. The updated field paths, comma separated if '
                                                  'there are multiple. You can update the following fields '
                                                  "for a space: `space_details`: Updates the space's "
                                                  'description and guidelines. You must pass both '
                                                  'description and guidelines in the update request as '
                                                  '`SpaceDetails`. If you only want to update one of the '
                                                  'fields, pass the existing value for t',
                                   'type': 'string'},
                                  {'name': 'useAdminAccess',
                                   'required': False,
                                   'description': "Optional. When `true`, the method runs using the user's "
                                                  'Google Workspace administrator privileges. The calling '
                                                  'user must be a Google Workspace administrator with the '
                                                  '[manage chat and spaces conversations '
                                                  'privilege](https://support.google.com/a/answer/13369245). '
                                                  'Requires the `chat.admin.spaces` [OAuth 2.0 '
                                                  'scope](https://developers.google.com/workspa',
                                   'type': 'boolean'}],
                 'body_json': True,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.spaces'},
                {'name': 'spaces_search',
                 'label': 'Spaces Search',
                 'category': 'Spaces',
                 'description': 'Returns a list of spaces in a Google Workspace organization. For an '
                                'example, see [Search for and manage '
                                'spaces](https://developers.google.com/workspace/chat/search-manage-admin). '
                                'When `use_admin_access` is set to `false`, the results are limited to '
                                'spaces where the calling user is a joined member. To search with '
                                'administrator privileges, set `use_admin_access` to `true`. Supports the '
                                'following types of '
                                '[authentication](https://developers.google.com/workspace/chat/authenticate-authorize): '
                                '- [User '
                                'authentication](https://developers.google.com/workspace/chat/authenticate-authorize-chat-user) '
                                'with',
                 'method': 'GET',
                 'path': 'v1/spaces:search',
                 'path_params': [],
                 'query_params': [{'name': 'pageSize',
                                   'required': False,
                                   'description': 'The maximum number of spaces to return. The service may '
                                                  'return fewer than this value. If unspecified, at most 100 '
                                                  'spaces are returned. The maximum value is 1000 when '
                                                  '`useAdminAccess` is set to `true`. Otherwise, the maximum '
                                                  'value is 100. If you use a value more than the maximum '
                                                  "value, it's automatically changed to the maximum value.",
                                   'type': 'integer'},
                                  {'name': 'useAdminAccess',
                                   'required': False,
                                   'description': "When `true`, the method runs using the user's Google "
                                                  'Workspace administrator privileges. The calling user must '
                                                  'be a Google Workspace administrator with the [manage chat '
                                                  'and spaces conversations '
                                                  'privilege](https://support.google.com/a/answer/13369245). '
                                                  'Requires either the `chat.admin.spaces.readonly` or '
                                                  '`chat.admin.spaces` [OAuth 2.0 scope](https://',
                                   'type': 'boolean'},
                                  {'name': 'pageToken',
                                   'required': False,
                                   'description': 'A token, received from the previous search spaces call. '
                                                  'Provide this parameter to retrieve the subsequent page. '
                                                  'When paginating, all other parameters provided should '
                                                  'match the call that provided the page token. Passing '
                                                  'different values to the other parameters might lead to '
                                                  'unexpected results.',
                                   'type': 'string'},
                                  {'name': 'query',
                                   'required': False,
                                   'description': 'Required. A search query. You can search by using the '
                                                  'following parameters when `useAdminAccess` is set to '
                                                  '`true`: - `create_time` - `customer` - `display_name` - '
                                                  '`external_user_allowed` - `last_active_time` - '
                                                  '`space_history_state` - `space_type` When '
                                                  '`useAdminAccess` is set to `false`: - `display_name` - '
                                                  '`external_user_allowed` - `space_type` `cre',
                                   'type': 'string'},
                                  {'name': 'orderBy',
                                   'required': False,
                                   'description': 'Optional. How the list of spaces is ordered. Supported '
                                                  'attributes to order by are: - '
                                                  '`membership_count.joined_direct_human_user_count` — '
                                                  'Denotes the count of human users that have directly '
                                                  'joined a space. - `last_active_time` — Denotes the time '
                                                  'when last eligible item is added to any topic of this '
                                                  'space. - `create_time` — Denotes the time of the sp',
                                   'type': 'string'}],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.spaces'},
                {'name': 'spaces_setup',
                 'label': 'Spaces Setup',
                 'category': 'Spaces',
                 'description': 'Creates a space and adds specified users to it. The calling user is '
                                "automatically added to the space, and shouldn't be specified as a "
                                'membership in the request. For an example, see [Set up a space with initial '
                                'members](https://developers.google.com/workspace/chat/set-up-spaces). To '
                                'specify the human members to add, add memberships with the appropriate '
                                '`membership.member.name`. To add a human user, use `users/{user}`, where '
                                '`{user}` can be the email address for the user. For users in the same '
                                'Workspace organization `{user}` can also be the `id` for the person from '
                                'the People API, or the `id` fo',
                 'method': 'POST',
                 'path': 'v1/spaces:setup',
                 'path_params': [],
                 'query_params': [],
                 'body_json': True,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.spaces'},
                {'name': 'spaces_space_events_get',
                 'label': 'Spaces Space Events Get',
                 'category': 'Spaces',
                 'description': 'Returns an event from a Google Chat space. The [event '
                                'payload](https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces.spaceEvents#SpaceEvent.FIELDS.oneof_payload) '
                                'contains the most recent version of the resource that changed. For example, '
                                'if you request an event about a new message but the message was later '
                                'updated, the server returns the updated `Message` resource in the event '
                                'payload. Note: The `permissionSettings` field is not returned in the Space '
                                'object of the Space event data for this request. Supports the following '
                                'types of [authentication](https://developers.google.c',
                 'method': 'GET',
                 'path': 'v1/{+name}',
                 'path_params': [{'name': 'name',
                                  'required': True,
                                  'description': 'Required. The resource name of the space event. Format: '
                                                 '`spaces/{space}/spaceEvents/{spaceEvent}`',
                                  'type': 'string'}],
                 'query_params': [],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.spaces'},
                {'name': 'spaces_space_events_list',
                 'label': 'Spaces Space Events List',
                 'category': 'Spaces',
                 'description': 'Lists events from a Google Chat space. For each event, the '
                                '[payload](https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces.spaceEvents#SpaceEvent.FIELDS.oneof_payload) '
                                'contains the most recent version of the Chat resource. For example, if you '
                                'list events about new space members, the server returns `Membership` '
                                'resources that contain the latest membership details. If new members were '
                                'removed during the requested period, the event payload contains an empty '
                                '`Membership` resource. Supports the following types of '
                                '[authentication](https://developers.google.com/workspace/chat/auth',
                 'method': 'GET',
                 'path': 'v1/{+parent}/spaceEvents',
                 'path_params': [{'name': 'parent',
                                  'required': True,
                                  'description': 'Required. Resource name of the [Google Chat '
                                                 'space](https://developers.google.com/workspace/chat/api/reference/rest/v1/spaces) '
                                                 'where the events occurred. Format: `spaces/{space}`.',
                                  'type': 'string'}],
                 'query_params': [{'name': 'pageToken',
                                   'required': False,
                                   'description': 'Optional. A page token, received from a previous list '
                                                  'space events call. Provide this to retrieve the '
                                                  'subsequent page. When paginating, all other parameters '
                                                  'provided to list space events must match the call that '
                                                  'provided the page token. Passing different values to the '
                                                  'other parameters might lead to unexpected results.',
                                   'type': 'string'},
                                  {'name': 'pageSize',
                                   'required': False,
                                   'description': 'Optional. The maximum number of space events returned. '
                                                  'The service might return fewer than this value. Negative '
                                                  'values return an `INVALID_ARGUMENT` error.',
                                   'type': 'integer'},
                                  {'name': 'filter',
                                   'required': False,
                                   'description': 'Required. A query filter. You must specify at least one '
                                                  'event type (`event_type`) using the has `:` operator. To '
                                                  'filter by multiple event types, use the `OR` operator. '
                                                  'Omit batch event types in your filter. The request '
                                                  'automatically returns any related batch events. For '
                                                  'example, if you filter by new reactions '
                                                  '(`google.workspace.chat.reaction.v1.cre',
                                   'type': 'string'}],
                 'body_json': False,
                 'body_required_fields': [],
                 'scope': 'https://www.googleapis.com/auth/chat.spaces'}]}

OPERATIONS = {row["name"]: row for row in CATALOG["operations"]}
assert len(OPERATIONS) == len(CATALOG["operations"]), "Duplicate Google Chat operations"
CHAT_SCOPES = ScopeRegistry(
    provider="google-chat",
    requirements={name: ScopeRequirement(scopes=(op["scope"],)) for name, op in OPERATIONS.items()},
    enforcement=Enforcement.STRICT,
)
