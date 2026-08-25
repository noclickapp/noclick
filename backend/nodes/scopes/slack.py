"""Slack endpoint → OAuth scope requirements.

Verified against Slack's published method docs (https://api.slack.com/methods),
so this registry runs at ``Enforcement.STRICT``: ``SlackOAuthCredential``'s
requested scopes are derived from this table and must equal it exactly.

Two structural facts drive the shape here:

- **Two tokens.** Slack's OAuth v2 exchange returns a bot (``xoxb-``) and a user
  (``xoxp-``) token with independently granted scopes. Write operations honor a
  per-operation ``send_as``, so their scope must be held on BOTH — those use
  ``ANY_VARIANT``. Reads hard-coded to one token declare that variant only.
- **Admin methods can't ride the shared app.** Slack refuses to install an app
  requesting ``admin.*`` scopes onto a non-Enterprise-Grid workspace, and the
  installer must be an Org Owner. Requesting them on the shared NoClick app
  would break Slack connect for every ordinary user, so the admin operations
  sit in the ``enterprise_grid_admin`` tier: excluded from the connect request,
  and runnable only with a user-supplied ``slack_bot_token`` from their own
  Grid admin app. Three legacy ``team.*`` reads share the tier but need a paid
  workspace admin's USER token, not Grid — see ``_LEGACY_ADMIN_NOTE``.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import (
    ANY_VARIANT,
    Enforcement,
    ScopeRegistry,
    ScopeRequirement,
)

BOT = "bot"
USER = "user"

#: Admin methods are Enterprise Grid only and need an Org Owner install.
GRID_ADMIN_TIER = "enterprise_grid_admin"

_GRID_NOTE = (
    "Slack admin methods require an Enterprise Grid workspace and an app "
    "installed by an Org Owner. Connect a Bot Token credential from your own "
    "Grid admin app that holds the scope shown above."
)

#: Slack gates ``conversations.connect:manage`` behind an admin install: an app
#: requesting it "can only be installed by a workspace owner or admin", which
#: would break self-install for every ordinary member of every workspace. The
#: scope is therefore excluded from the shared connect request and the
#: operations needing it are satisfied by a user-supplied bot token instead.
CONNECT_ADMIN_TIER = "slack_connect_admin"

_CONNECT_ADMIN_NOTE = (
    "Slack only grants conversations.connect:manage to apps installed by a "
    "workspace admin. Connect a Bot Token credential from your own app (with "
    "that scope) that an admin has installed to the workspace."
)


def _bot(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes, variant=BOT)


def _user(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes, variant=USER)


def _any(*scopes: str) -> ScopeRequirement:
    """Scope needed on whichever token ``send_as`` selects."""
    return ScopeRequirement(scopes=scopes, variant=ANY_VARIANT)


def _split(bot: tuple[str, ...] | str, user: tuple[str, ...] | str) -> ScopeRequirement:
    """``send_as`` endpoint whose required scope differs per token.

    Slack defines some scopes on only one token type (``channels:join`` /
    ``channels:manage`` are bot scopes, ``channels:write`` is the user-token
    equivalent), so folding a union into both requested lists would ask each
    token for scopes the other owns.
    """
    return ScopeRequirement(scopes=bot, variant=ANY_VARIANT, user_scopes=user)  # type: ignore[arg-type]


def _grid(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(
        scopes=scopes,
        variant=BOT,
        tier=GRID_ADMIN_TIER,
        credential_types=("slack_bot_token",),
        note=_GRID_NOTE,
    )


_CONNECT_ADMIN = ScopeRequirement(
    scopes=("conversations.connect:manage",),
    variant=BOT,
    tier=CONNECT_ADMIN_TIER,
    credential_types=("slack_bot_token",),
    note=_CONNECT_ADMIN_NOTE,
)


# Channel reads span every conversation surface; Slack requires the scope for
# each surface the call may touch.
_READ_CHANNELS = ("channels:read", "groups:read", "im:read", "mpim:read")
_READ_HISTORY = (
    "channels:history",
    "groups:history",
    "im:history",
    "mpim:history",
)
# Public channels are managed with channels:manage (bot) / channels:write
# (user); private channels always need the groups: equivalent.
_MANAGE_CHANNELS_BOT = ("channels:manage", "groups:write")
_MANAGE_CHANNELS_USER = ("channels:write", "groups:write")
_MANAGE_CHANNELS = _split(bot=_MANAGE_CHANNELS_BOT, user=_MANAGE_CHANNELS_USER)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- connectivity / identity (no scope beyond authentication) --------
    "api.test": _any(),
    "auth.test": _any(),
    "auth.revoke": _any(),
    "bots.info": _bot("users:read"),
    # -- messaging -------------------------------------------------------
    "chat.postMessage": _any("chat:write"),
    "chat.update": _any("chat:write"),
    "chat.delete": _any("chat:write"),
    "chat.postEphemeral": _any("chat:write"),
    "chat.meMessage": _any("chat:write"),
    "chat.scheduleMessage": _any("chat:write"),
    "chat.deleteScheduledMessage": _any("chat:write"),
    "chat.scheduledMessages.list": _any("chat:write"),
    "chat.getPermalink": _any(),
    "chat.unfurl": _any("links:write"),
    # -- conversations: read ---------------------------------------------
    "conversations.list": _user(*_READ_CHANNELS),
    "conversations.info": _user(*_READ_CHANNELS),
    "conversations.members": _user("channels:read", "groups:read"),
    "conversations.history": _user(*_READ_HISTORY),
    "conversations.replies": _user(*_READ_HISTORY),
    "conversations.mark": _user("channels:write", "groups:write"),
    "users.conversations": _bot(*_READ_CHANNELS),
    # -- conversations: manage -------------------------------------------
    "conversations.create": _MANAGE_CHANNELS,
    "conversations.archive": _MANAGE_CHANNELS,
    "conversations.unarchive": _MANAGE_CHANNELS,
    "conversations.rename": _MANAGE_CHANNELS,
    "conversations.invite": _MANAGE_CHANNELS,
    "conversations.kick": _MANAGE_CHANNELS,
    "conversations.leave": _MANAGE_CHANNELS,
    "conversations.setTopic": _MANAGE_CHANNELS,
    "conversations.setPurpose": _MANAGE_CHANNELS,
    "conversations.join": _split(bot="channels:join", user="channels:write"),
    "conversations.open": _bot("im:write", "mpim:write"),
    "conversations.close": _bot("im:write", "mpim:write"),
    "conversations.canvases.create": _bot("canvases:write"),
    # -- Slack Connect ----------------------------------------------------
    "conversations.inviteShared": _bot("conversations.connect:write"),
    "conversations.acceptSharedInvite": _bot("conversations.connect:write"),
    # connect:manage endpoints are admin-install gated — see CONNECT_ADMIN_TIER.
    "conversations.approveSharedInvite": _CONNECT_ADMIN,
    "conversations.declineSharedInvite": _CONNECT_ADMIN,
    "conversations.listConnectInvites": _CONNECT_ADMIN,
    "conversations.requestSharedInvite.approve": _CONNECT_ADMIN,
    "conversations.requestSharedInvite.deny": _CONNECT_ADMIN,
    "conversations.requestSharedInvite.list": _CONNECT_ADMIN,
    "conversations.externalInvitePermissions.set": _CONNECT_ADMIN,
    # -- users -------------------------------------------------------------
    "users.list": _bot("users:read"),
    "users.info": _bot("users:read"),
    "users.lookupByEmail": _bot("users:read.email"),
    "users.getPresence": _bot("users:read"),
    "users.setPresence": _user("users:write"),
    "users.setActive": _user("users:write"),
    "users.profile.get": _user("users.profile:read"),
    "users.profile.set": _user("users.profile:write"),
    "users.deletePhoto": _user("users.profile:write"),
    # -- reactions / pins / bookmarks / stars -------------------------------
    "reactions.add": _any("reactions:write"),
    "reactions.remove": _any("reactions:write"),
    "reactions.get": _user("reactions:read"),
    "reactions.list": _user("reactions:read"),
    "pins.add": _any("pins:write"),
    "pins.remove": _any("pins:write"),
    "pins.list": _user("pins:read"),
    "bookmarks.add": _any("bookmarks:write"),
    "bookmarks.edit": _any("bookmarks:write"),
    "bookmarks.remove": _any("bookmarks:write"),
    "bookmarks.list": _user("bookmarks:read"),
    "stars.add": _user("stars:write"),
    "stars.remove": _user("stars:write"),
    "stars.list": _user("stars:read"),
    # -- reminders (user token only; Slack has no bot equivalent) -----------
    "reminders.add": _user("reminders:write"),
    "reminders.complete": _user("reminders:write"),
    "reminders.delete": _user("reminders:write"),
    "reminders.info": _user("reminders:read"),
    "reminders.list": _user("reminders:read"),
    # -- usergroups ---------------------------------------------------------
    "usergroups.create": _any("usergroups:write"),
    "usergroups.update": _any("usergroups:write"),
    "usergroups.enable": _any("usergroups:write"),
    "usergroups.disable": _any("usergroups:write"),
    "usergroups.list": _bot("usergroups:read"),
    "usergroups.users.list": _bot("usergroups:read"),
    "usergroups.users.update": _any("usergroups:write"),
    # -- do not disturb ------------------------------------------------------
    "dnd.info": _bot("dnd:read"),
    "dnd.teamInfo": _bot("dnd:read"),
    "dnd.setSnooze": _user("dnd:write"),
    "dnd.endSnooze": _user("dnd:write"),
    "dnd.endDnd": _user("dnd:write"),
    # -- workspace -----------------------------------------------------------
    "emoji.list": _bot("emoji:read"),
    "team.info": _bot("team:read"),
    # -- search (user token only) --------------------------------------------
    "search.all": _user("search:read"),
    "search.messages": _user("search:read"),
    "search.files": _user("search:read"),
    # -- files ----------------------------------------------------------------
    "files.list": _bot("files:read"),
    "files.info": _bot("files:read"),
    "files.delete": _any("files:write"),
    "files.getUploadURLExternal": _any("files:write"),
    "files.completeUploadExternal": _any("files:write"),
    "files.comments.delete": _any("files:write"),
    "files.sharedPublicURL": _user("files:write"),
    "files.revokePublicURL": _user("files:write"),
    "files.remote.add": _bot("remote_files:write"),
    "files.remote.update": _bot("remote_files:write"),
    "files.remote.remove": _bot("remote_files:write"),
    "files.remote.info": _bot("remote_files:read"),
    "files.remote.list": _bot("remote_files:read"),
    "files.remote.share": _bot("remote_files:share"),
}


# ---------------------------------------------------------------------------
# Enterprise Grid admin methods — excluded from the shared app's request.
# ---------------------------------------------------------------------------

_GRID_BY_SCOPE: dict[str, tuple[str, ...]] = {
    "admin.analytics:read": ("admin.analytics.getFile",),
    "admin.apps.activities:read": ("admin.apps.activities.list",),
    "admin.apps:read": (
        "admin.apps.approved.list",
        "admin.apps.restricted.list",
        "admin.apps.requests.list",
        "admin.apps.config.lookup",
    ),
    "admin.apps:write": (
        "admin.apps.approve",
        "admin.apps.restrict",
        "admin.apps.clearResolution",
        "admin.apps.uninstall",
        "admin.apps.requests.cancel",
        "admin.apps.config.set",
        "apps.uninstall",
    ),
    "auditlogs:read": ("admin.audit.anomaly.allow.getItem",),
    "admin.audit:write": ("admin.audit.anomaly.allow.updateItem",),
    "admin.barriers:read": ("admin.barriers.list",),
    "admin.barriers:write": (
        "admin.barriers.create",
        "admin.barriers.delete",
        "admin.barriers.update",
    ),
    "admin.conversations:read": (
        "admin.conversations.ekm.listOriginalConnectedChannelInfo",
        "admin.conversations.getConversationPrefs",
        "admin.conversations.getCustomRetention",
        "admin.conversations.getTeams",
        "admin.conversations.lookup",
        "admin.conversations.search",
        "admin.conversations.restrictAccess.listGroups",
    ),
    "admin.conversations:write": (
        "admin.conversations.archive",
        "admin.conversations.bulkArchive",
        "admin.conversations.bulkDelete",
        "admin.conversations.bulkMove",
        "admin.conversations.convertToPrivate",
        "admin.conversations.convertToPublic",
        "admin.conversations.create",
        "admin.conversations.delete",
        "admin.conversations.disconnectShared",
        "admin.conversations.invite",
        "admin.conversations.removeCustomRetention",
        "admin.conversations.rename",
        "admin.conversations.setConversationPrefs",
        "admin.conversations.setCustomRetention",
        "admin.conversations.setTeams",
        "admin.conversations.unarchive",
        "admin.conversations.restrictAccess.addGroup",
        "admin.conversations.restrictAccess.removeGroup",
    ),
    "admin.functions:read": (
        "admin.functions.list",
        "admin.functions.permissions.lookup",
    ),
    "admin.functions:write": ("admin.functions.permissions.set",),
    "admin.invites:read": (
        "admin.inviteRequests.list",
        "admin.inviteRequests.approved.list",
        "admin.inviteRequests.denied.list",
    ),
    "admin.invites:write": (
        "admin.inviteRequests.approve",
        "admin.inviteRequests.deny",
    ),
    "admin.roles:read": ("admin.roles.listAssignments",),
    "admin.roles:write": (
        "admin.roles.addAssignments",
        "admin.roles.removeAssignments",
    ),
    "admin.teams:read": (
        "admin.teams.list",
        "admin.teams.admins.list",
        "admin.teams.owners.list",
        "admin.teams.settings.info",
        "admin.emoji.list",
    ),
    "admin.teams:write": (
        "admin.teams.create",
        "admin.teams.settings.setDefaultChannels",
        "admin.teams.settings.setDescription",
        "admin.teams.settings.setDiscoverability",
        "admin.teams.settings.setIcon",
        "admin.teams.settings.setName",
        "admin.emoji.add",
        "admin.emoji.addAlias",
        "admin.emoji.remove",
        "admin.emoji.rename",
    ),
    "admin.usergroups:read": ("admin.usergroups.listChannels",),
    "admin.usergroups:write": (
        "admin.usergroups.addChannels",
        "admin.usergroups.addTeams",
        "admin.usergroups.removeChannels",
    ),
    "admin.users:read": (
        "admin.users.list",
        "admin.users.getExpiration",
        "admin.users.session.list",
        "admin.users.session.getSettings",
        "admin.users.unsupportedVersions.export",
        "admin.auth.policy.getEntities",
    ),
    "admin.users:write": (
        "admin.users.assign",
        "admin.users.invite",
        "admin.users.remove",
        "admin.users.setAdmin",
        "admin.users.setExpiration",
        "admin.users.setOwner",
        "admin.users.setRegular",
        "admin.users.session.invalidate",
        "admin.users.session.reset",
        "admin.users.session.resetBulk",
        "admin.users.session.clearSettings",
        "admin.users.session.setSettings",
        "admin.auth.policy.assignEntities",
        "admin.auth.policy.removeEntities",
    ),
    "admin.workflows:read": (
        "admin.workflows.search",
        "admin.workflows.permissions.lookup",
        "admin.workflows.triggers.types.permissions.lookup",
    ),
    "admin.workflows:write": (
        "admin.workflows.collaborators.add",
        "admin.workflows.collaborators.remove",
        "admin.workflows.triggers.types.permissions.set",
        "admin.workflows.unpublish",
    ),
}

for _scope, _endpoints in _GRID_BY_SCOPE.items():
    for _endpoint in _endpoints:
        _REQUIREMENTS[_endpoint] = _grid(_scope)

# Legacy workspace-admin reads. Unlike the admin.* family these are not Grid
# methods: Slack gates them on the catch-all `admin` USER scope on any paid
# workspace. Still excluded from the shared connect request (workspace-admin
# power for every user) and satisfied by a pasted token — but that token must
# be an admin's xoxp- user token, so the note says so.
_LEGACY_ADMIN_NOTE = (
    "This method needs a user token (xoxp-) carrying the legacy `admin` scope "
    "from a workspace admin on a paid Slack plan. Paste it as a Bot Token "
    "credential."
)
for _endpoint in ("team.accessLogs", "team.billableInfo", "team.integrationLogs"):
    _REQUIREMENTS[_endpoint] = ScopeRequirement(
        scopes=("admin",),
        variant=USER,
        tier=GRID_ADMIN_TIER,
        credential_types=("slack_bot_token",),
        note=_LEGACY_ADMIN_NOTE,
    )


# Event subscriptions, not method calls. The trigger operations in
# SlackNode._trigger_event_map receive these over the Events API, and Slack
# gates delivery on the BOT token holding the scope — no endpoint call implies
# them, so an endpoint-derived list alone would silently drop every trigger.
_EVENT_SCOPES: tuple[str, ...] = (
    "app_mentions:read",  # app_mention  -> on_app_mention
    "channels:history",  # message.channels -> on_channel_message
    "groups:history",  # message.groups
    "im:history",  # message.im
    "mpim:history",  # message.mpim
    "reactions:read",  # reaction_added -> on_reaction_added
    # channel_created / member_joined_channel / file_shared are covered by
    # channels:read + groups:read + files:read, which endpoints already imply.
)

# Granted today and not implied by any endpoint, because the calls that would
# use them are hard-coded to the other token (bookmarks.list, pins.list and the
# conversations reads run on the user token; conversations.open/close on the
# bot). Dropping a granted scope forces every existing user to re-authorize for
# no functional gain, so they are retained deliberately rather than derived
# away. Remove only alongside a planned re-auth.
_RETAINED_BOT: tuple[str, ...] = ("bookmarks:read", "pins:read")
_RETAINED_USER: tuple[str, ...] = ("im:write", "mpim:write")


SLACK_SCOPES = ScopeRegistry(
    provider="slack",
    requirements=_REQUIREMENTS,
    enforcement=Enforcement.STRICT,
    extra_scopes={
        BOT: _EVENT_SCOPES + _RETAINED_BOT,
        USER: _RETAINED_USER,
    },
)


# Operation names whose every API call lands on a Grid-admin endpoint. Kept
# here so ``get_config_schema`` can mark them in the operation picker without
# instantiating a node to walk the handler map; the coverage test re-derives
# this set from the AST and fails if it drifts.
GRID_ADMIN_OPERATIONS: frozenset[str] = frozenset(
    {
        "add_channels_to_usergroup",
        "add_custom_emoji",
        "add_emoji_alias",
        "add_idp_group_to_channel",
        "add_role_assignments",
        "add_teams_to_usergroup",
        "add_workflow_collaborators",
        "approve_app_for_installation",
        "approve_invite_request",
        "archive_conversation_as_admin",
        "assign_entities_to_auth_policy",
        "assign_user_to_team",
        "bulk_archive_conversations",
        "bulk_delete_conversations",
        "bulk_move_conversations_to_team",
        "bulk_reset_user_sessions",
        "cancel_app_request",
        "clear_app_resolution",
        "clear_user_session_settings",
        "convert_channel_to_private",
        "convert_channel_to_public",
        "create_admin_conversation",
        "create_information_barrier",
        "create_team",
        "delete_conversation",
        "delete_information_barrier",
        "deny_invite_request",
        "disconnect_shared_channel",
        "export_unsupported_version_users",
        "get_allowed_audit_anomaly_item",
        "get_analytics_file_for_date",
        "get_channel_retention_settings",
        "get_conversation_preferences",
        "get_entities_for_auth_policy",
        "get_team_billable_information",
        "get_team_settings",
        "get_user_expiration",
        "get_user_session_settings",
        "get_workspace_access_logs",
        "get_workspace_integration_logs",
        "invalidate_user_session",
        "invite_user_to_team",
        "invite_users_to_conversation_as_admin",
        "list_app_activity_logs",
        "list_app_requests",
        "list_approved_apps",
        "list_approved_invite_requests",
        "list_channels_in_usergroup",
        "list_custom_emoji",
        "list_denied_invite_requests",
        "list_ekm_original_channel_info",
        "list_functions",
        "list_idp_groups_for_channel",
        "list_information_barriers",
        "list_invite_requests",
        "list_restricted_apps",
        "list_role_assignments",
        "list_team_admins",
        "list_team_owners",
        "list_teams",
        "list_teams_for_conversation",
        "list_user_sessions",
        "list_users_in_team",
        "lookup_app_configuration",
        "lookup_conversations",
        "lookup_function_permissions",
        "lookup_workflow_permissions",
        "lookup_workflow_trigger_type_permissions",
        "remove_channel_retention_settings",
        "remove_channels_from_usergroup",
        "remove_custom_emoji",
        "remove_entities_from_auth_policy",
        "remove_idp_group_from_channel",
        "remove_role_assignments",
        "remove_user_from_team",
        "remove_workflow_collaborators",
        "rename_conversation_as_admin",
        "rename_custom_emoji",
        "reset_user_session",
        "restrict_app",
        "search_conversations",
        "search_workflows",
        "set_app_configuration",
        "set_channel_retention_settings",
        "set_conversation_preferences",
        "set_default_channels_for_team",
        "set_function_permissions",
        "set_team_description",
        "set_team_discoverability",
        "set_team_icon",
        "set_team_name",
        "set_teams_for_conversation",
        "set_user_as_admin",
        "set_user_as_owner",
        "set_user_as_regular",
        "set_user_expiration",
        "set_user_session_settings",
        "set_workflow_trigger_type_permissions",
        "unarchive_conversation_as_admin",
        "uninstall_app",
        "uninstall_app_from_workspace",
        "unpublish_workflow",
        "update_allowed_audit_anomaly_item",
        "update_information_barrier",
    }
)


#: Operations whose endpoints need conversations.connect:manage (see
#: CONNECT_ADMIN_TIER). Materialized like GRID_ADMIN_OPERATIONS so
#: get_config_schema can mark the picker; the coverage test re-derives it.
CONNECT_ADMIN_OPERATIONS: frozenset[str] = frozenset(
    {
        "approve_slack_connect_channel_invite",
        "approve_slack_connect_invite_request",
        "decline_shared_channel_invite",
        "deny_slack_connect_invite_request",
        "list_slack_connect_invite_requests",
        "list_slack_connect_invites",
        "set_channel_external_invite_permissions",
    }
)
