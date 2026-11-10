"""Microsoft (Graph / Fabric) operation → OAuth scope requirements.

Seven nodes share a permission vocabulary: six speak Microsoft Graph (Outlook,
OneDrive, Word, Excel, Teams, To Do) and OneLake speaks the two Azure/Fabric
audiences that sit next to it. OneDrive, Word, Excel and To Do keep their
registries in modules of their own (``onedrive.py``, ``word.py``, ``excel.py``,
``microsoft_todo.py``).

Four facts drive the shape here:

- **Scopes are absolute URIs.** Entra ID resource scopes are requested as
  ``https://graph.microsoft.com/<Permission>``, not the bare permission name the
  docs print. The requirement strings must match the requested list character
  for character, so every entry goes through :func:`_graph` / the OneLake
  constants rather than being written out by hand.
- **Delegated, not application.** These nodes act as the signed-in user, so the
  mapping is taken from the "Delegated (work or school account)" row of each
  method's permission table. Application permissions (``*.All`` variants granted
  to the app itself) never apply.
- **Graph permissions are alternatives, not a conjunction.** A method's table
  lists a least-privileged permission plus higher-privileged ones that also
  satisfy it. Each entry below names the ONE documented alternative the node
  actually requests — that keeps the requirement true and the derived union a
  subset of the connect request. Where the node requests only a Read/ReadWrite
  pair member the docs do not list, the operation is ``unmapped`` instead.
- **OneLake is two audiences, not one.** The DFS/Blob/Table endpoints only
  accept Storage-audience tokens (``storage.azure.com``); the Fabric Core
  shortcut / settings / data-access-role endpoints need the Fabric audience.
  The node already partitions its operations that way; this table mirrors it.

Everything runs at ``Enforcement.SUBSET``: the tables are derived from the
published per-method permission tables, but the requested lists also carry
``offline_access`` and ``User.Read``, which no single operation implies.

Known gaps are listed in each registry's ``unmapped`` with a ``MISSING SCOPE``
comment naming the permission the node would have to request. They are recorded,
not fixed — adding a scope to ``x-oauth-scopes`` forces every existing user to
re-authorize, so those are batched decisions.

Sources: Microsoft Graph permissions reference and the per-method permission
tables under https://learn.microsoft.com/graph/api/, the change-notification
permission table on ``POST /subscriptions``, and the Microsoft Fabric REST API
"Required Delegated Scopes" for the OneLake surfaces.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

GRAPH = "https://graph.microsoft.com/"

#: OneLake DFS / Blob / Table endpoints. "OneLake only supports tokens in the
#: Storage audience" (Fabric docs, "How do I connect to OneLake?").
ONELAKE_STORAGE = "https://storage.azure.com/user_impersonation"
#: Fabric Core APIs (shortcuts, OneLake settings, data access roles). Every one
#: of them documents "Required Delegated Scopes: OneLake.ReadWrite.All".
ONELAKE_FABRIC = "https://api.fabric.microsoft.com/OneLake.ReadWrite.All"


def _graph(*permissions: str) -> ScopeRequirement:
    """A Graph delegated permission, expanded to the requested scope URI."""
    return ScopeRequirement(scopes=tuple(GRAPH + p for p in permissions))


def _onelake(scope: str, note: str = "") -> ScopeRequirement:
    return ScopeRequirement(scopes=(scope,), note=note)


# OneDrive and Word are driveItem clients: every call they make resolves to this one permission.
_FILES_ALL = _graph("Files.ReadWrite.All")


# ===========================================================================
# Outlook  (automation-outlook)
# ===========================================================================
# Requests: Mail.Send, Mail.Read, Mail.ReadWrite, MailboxSettings.ReadWrite,
# Calendars.Read, Calendars.ReadWrite, Calendars.ReadWrite.Shared,
# Contacts.Read, Contacts.ReadWrite, User.Read, offline_access.

_MAIL_READ = _graph("Mail.Read")
_MAIL_WRITE = _graph("Mail.ReadWrite")
_MAIL_SEND = _graph("Mail.Send")
_MAILBOX_WRITE = _graph("MailboxSettings.ReadWrite")
_CAL_READ = _graph("Calendars.Read")
_CAL_WRITE = _graph("Calendars.ReadWrite")
_CONTACTS_READ = _graph("Contacts.Read")
_CONTACTS_WRITE = _graph("Contacts.ReadWrite")

_OUTLOOK_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- messages: read ----------------------------------------------------
    "read_inbox_emails": _MAIL_READ,  # mailFolder: List messages
    "get_email_message": _MAIL_READ,  # Get message
    "get_email_mime_content": _MAIL_READ,  # Get message ($value)
    "get_email_attachments": _MAIL_READ,  # List attachments
    # -- messages: send ----------------------------------------------------
    "send_email_message": _MAIL_SEND,  # user: sendMail
    "send_mime_message": _MAIL_SEND,  # user: sendMail (MIME)
    "send_email_draft": _MAIL_SEND,  # message: send
    "reply_to_email_message": _MAIL_SEND,  # message: reply / replyAll
    "forward_email_message": _MAIL_SEND,  # message: forward
    # -- messages: write ---------------------------------------------------
    "create_email_draft": _MAIL_WRITE,  # user: Create message
    "create_reply_draft": _MAIL_WRITE,  # message: createReply
    "create_reply_all_draft": _MAIL_WRITE,  # message: createReplyAll
    "create_forward_draft": _MAIL_WRITE,  # message: createForward
    "update_email_message_properties": _MAIL_WRITE,  # Update message
    "mark_email_as_read_unread": _MAIL_WRITE,  # Update message
    "move_email_to_folder": _MAIL_WRITE,  # message: move
    "copy_message_to_folder": _MAIL_WRITE,  # message: copy
    "delete_email_message": _MAIL_WRITE,  # message: move -> deleteditems
    "add_attachment_to_message": _MAIL_WRITE,  # message: Add attachment
    "delete_attachment_from_message": _MAIL_WRITE,  # Delete attachment (message)
    # -- mail folders ------------------------------------------------------
    "list_mail_folders": _MAIL_READ,  # user: List mailFolders
    "create_mail_folder": _MAIL_WRITE,  # Create mailFolder / childFolder
    "update_mail_folder": _MAIL_WRITE,  # Update mailFolder
    "delete_mail_folder": _MAIL_WRITE,  # Delete mailFolder
    "copy_mail_folder": _MAIL_WRITE,  # mailFolder: copy
    "move_mail_folder": _MAIL_WRITE,  # mailFolder: move
    # -- mailbox settings --------------------------------------------------
    "get_mailbox_settings": _MAILBOX_WRITE,  # Get mailboxSettings
    "update_auto_reply_settings": _MAILBOX_WRITE,  # Update mailboxSettings
    # -- inbox rules / categories (writes only; see unmapped for the reads) --
    "create_inbox_rule": _MAILBOX_WRITE,  # mailFolder: Create messageRule
    "update_inbox_rule": _MAILBOX_WRITE,  # Update messageRule
    "delete_inbox_rule": _MAILBOX_WRITE,  # Delete messageRule
    "create_message_category": _MAILBOX_WRITE,  # Create outlookCategory
    "update_message_category": _MAILBOX_WRITE,  # Update outlookCategory
    "delete_message_category": _MAILBOX_WRITE,  # Delete outlookCategory
    # The read halves document only MailboxSettings.Read, but Graph's
    # ReadWrite subsumes it in practice — live-verified 2026-07-22
    # (list_inbox_rules and list_message_categories both succeed with a
    # token granted only MailboxSettings.ReadWrite).
    "list_inbox_rules": _MAILBOX_WRITE,  # mailFolder: List messageRules
    "get_inbox_rule": _MAILBOX_WRITE,  # Get messageRule
    "list_message_categories": _MAILBOX_WRITE,  # List outlookCategories
    "get_message_category": _MAILBOX_WRITE,  # Get outlookCategory
    # -- mail triggers (POST /subscriptions on a message resource) ---------
    "on_email_received": _MAIL_READ,
    "on_email_updated": _MAIL_READ,
    "on_email_deleted": _MAIL_READ,
    "on_email_change": _MAIL_READ,
    # -- events: read ------------------------------------------------------
    "list_calendar_events": _CAL_READ,  # calendar: List events
    "get_calendar_event": _CAL_READ,  # Get event
    "list_recurring_event_instances": _CAL_READ,  # event: List instances
    "get_calendar_view": _CAL_READ,  # calendar: List calendarView
    "get_calendar_view_delta": _CAL_READ,  # event: delta
    "reminder_view": _CAL_READ,  # user: reminderView
    "get_free_busy_schedule": _CAL_READ,  # calendar: getSchedule
    "forward_calendar_event": _CAL_READ,  # event: forward
    "list_event_attachments": _CAL_READ,  # event: List attachments
    "get_event_attachment": _CAL_READ,  # Get attachment (event)
    # -- events: write -----------------------------------------------------
    "create_calendar_event": _CAL_WRITE,  # calendar: Create event
    "update_calendar_event": _CAL_WRITE,  # Update event
    "delete_calendar_event": _CAL_WRITE,  # Delete event
    "cancel_calendar_event": _CAL_WRITE,  # event: cancel
    "accept_calendar_event_invitation": _CAL_WRITE,  # event: accept
    "decline_calendar_event_invitation": _CAL_WRITE,  # event: decline
    "tentatively_accept_calendar_event_invitation": _CAL_WRITE,
    "dismiss_event_reminder": _CAL_WRITE,  # event: dismissReminder
    "snooze_event_reminder": _CAL_WRITE,  # event: snoozeReminder
    "add_event_attachment": _CAL_WRITE,  # event: Add attachment
    "delete_event_attachment": _CAL_WRITE,  # Delete attachment (event)
    # -- calendars / groups / permissions ----------------------------------
    "list_calendars": _CAL_READ,  # user: List calendars
    "get_calendar": _CAL_READ,  # Get calendar
    "create_calendar": _CAL_WRITE,  # user: Create calendar
    "update_calendar": _CAL_WRITE,  # Update calendar
    "delete_calendar": _CAL_WRITE,  # Delete calendar
    "list_calendar_groups": _CAL_READ,  # user: List calendarGroups
    "get_calendar_group": _CAL_READ,  # Get calendarGroup
    "create_calendar_group": _CAL_WRITE,  # user: Create calendarGroup
    "update_calendar_group": _CAL_WRITE,  # Update calendarGroup
    "delete_calendar_group": _CAL_WRITE,  # Delete calendarGroup
    "list_calendars_in_group": _CAL_READ,  # calendarGroup: List calendars
    "create_calendar_in_group": _CAL_WRITE,  # calendarGroup: Create calendar
    "list_calendar_permissions": _CAL_READ,  # calendar: List calendarPermissions
    "get_calendar_permission": _CAL_READ,  # Get calendarPermission
    "create_calendar_permission": _CAL_WRITE,  # calendar: Create calendarPermission
    "update_calendar_permission": _CAL_WRITE,  # Update calendarPermission
    "delete_calendar_permission": _CAL_WRITE,  # Delete calendarPermission
    # findMeetingTimes is the one method documented against the .Shared pair.
    "find_available_meeting_times": _graph("Calendars.ReadWrite.Shared"),
    # -- calendar triggers (POST /subscriptions on an event resource) ------
    "on_calendar_event_created": _CAL_READ,
    "on_calendar_event_updated": _CAL_READ,
    "on_calendar_event_deleted": _CAL_READ,
    "on_calendar_event_change": _CAL_READ,
    # -- contacts ----------------------------------------------------------
    "list_contacts": _CONTACTS_READ,  # user: List contacts
    "get_contact_person": _CONTACTS_READ,  # Get contact
    "create_contact_person": _CONTACTS_WRITE,  # user: Create contact
    "update_contact_person": _CONTACTS_WRITE,  # Update contact
    "delete_contact_person": _CONTACTS_WRITE,  # Delete contact
    "list_contact_folders": _CONTACTS_READ,  # user: List contactFolders
    "get_contact_folder": _CONTACTS_READ,  # Get contactFolder
    "create_contact_folder": _CONTACTS_WRITE,  # Create contactFolder
    "update_contact_folder": _CONTACTS_WRITE,  # Update contactFolder
    "delete_contact_folder": _CONTACTS_WRITE,  # Delete contactFolder
}

OUTLOOK_SCOPES = ScopeRegistry(
    provider="outlook",
    requirements=_OUTLOOK_REQUIREMENTS,
    unmapped=(
        # MISSING SCOPE: Place.Read.All. GET /places/microsoft.graph.roomList
        # documents Place.Read.All (higher: Place.ReadWrite.All); the node
        # requests neither, so room-list lookup can only 403 on work/school
        # accounts (personal MSA accounts reject the Places API outright —
        # "not supported for MSA accounts", live-verified 2026-07-22).
        "get_available_room_lists",
        # GET /me/calendars/{id}/allowedCalendarSharingRoles(User='...') has no
        # v1.0 reference page, so no permission is documented for it.
        "allowed_calendar_sharing_roles",
    ),
)


# ===========================================================================
# Microsoft Teams  (automation-microsoft-teams)
# ===========================================================================
# Requests: User.Read, Team.ReadBasic.All, Team.Create, Channel.ReadBasic.All,
# Channel.Create, Channel.Delete.All, ChannelMessage.Read.All,
# ChannelMessage.Send, Chat.ReadWrite, ChatMessage.Send,
# TeamMember.ReadWrite.All, TeamsAppInstallation.ReadWriteForTeam,
# TeamsTab.ReadWriteForTeam, OnlineMeetings.ReadWrite, Presence.Read.All.

_TEAMS_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- teams -------------------------------------------------------------
    "list_joined_teams": _graph("Team.ReadBasic.All"),  # user: List joinedTeams
    "get_team": _graph("Team.ReadBasic.All"),  # Get team
    "create_team": _graph("Team.Create"),  # Create team
    # -- channels ----------------------------------------------------------
    "list_channels": _graph("Channel.ReadBasic.All"),  # team: List channels
    "get_channel": _graph("Channel.ReadBasic.All"),  # Get channel
    "create_channel": _graph("Channel.Create"),  # team: Create channel
    "delete_channel": _graph("Channel.Delete.All"),  # Delete channel
    # -- channel messages --------------------------------------------------
    "list_channel_messages": _graph("ChannelMessage.Read.All"),
    "get_channel_message": _graph("ChannelMessage.Read.All"),
    "list_channel_message_replies": _graph("ChannelMessage.Read.All"),
    "send_channel_message": _graph("ChannelMessage.Send"),
    "reply_channel_message": _graph("ChannelMessage.Send"),
    "on_channel_message": _graph("ChannelMessage.Read.All"),  # /subscriptions
    # -- channel tabs ------------------------------------------------------
    "list_channel_tabs": _graph("TeamsTab.ReadWriteForTeam"),
    "add_channel_tab": _graph("TeamsTab.ReadWriteForTeam"),
    "delete_channel_tab": _graph("TeamsTab.ReadWriteForTeam"),
    # -- team membership ---------------------------------------------------
    "list_team_members": _graph("TeamMember.ReadWrite.All"),
    "add_team_member": _graph("TeamMember.ReadWrite.All"),
    "remove_team_member": _graph("TeamMember.ReadWrite.All"),
    # -- installed apps ----------------------------------------------------
    "list_installed_apps": _graph("TeamsAppInstallation.ReadWriteForTeam"),
    "install_app": _graph("TeamsAppInstallation.ReadWriteForTeam"),
    "uninstall_app": _graph("TeamsAppInstallation.ReadWriteForTeam"),
    # -- chats -------------------------------------------------------------
    "list_chats": _graph("Chat.ReadWrite"),  # user: List chats
    "get_chat": _graph("Chat.ReadWrite"),  # Get chat
    "create_chat": _graph("Chat.ReadWrite"),  # Create chat
    "list_chat_members": _graph("Chat.ReadWrite"),  # chat: List members
    "list_chat_messages": _graph("Chat.ReadWrite"),  # chat: List messages
    "get_chat_message": _graph("Chat.ReadWrite"),  # Get chatMessage (chat)
    "send_chat_message": _graph("ChatMessage.Send"),  # chat: Send message
    "on_chat_message": _graph("Chat.ReadWrite"),  # /subscriptions
    # -- meetings / presence ------------------------------------------------
    "create_online_meeting": _graph("OnlineMeetings.ReadWrite"),
    "get_online_meeting": _graph("OnlineMeetings.ReadWrite"),
    "get_my_presence": _graph("Presence.Read.All"),  # Get presence
    "get_user_presence": _graph("Presence.Read.All"),  # Get another user's
}

MICROSOFT_TEAMS_SCOPES = ScopeRegistry(
    provider="microsoft-teams",
    requirements=_TEAMS_REQUIREMENTS,
    unmapped=(
        # MISSING SCOPE: TeamSettings.ReadWrite.All. Update/archive/unarchive
        # team document TeamSettings.ReadWrite.All (higher: Group.ReadWrite.All,
        # Directory.ReadWrite.All). Team.ReadBasic.All + Team.Create do not
        # cover any of them.
        "update_team",
        "archive_team",
        "unarchive_team",
        # MISSING SCOPE: ChannelSettings.ReadWrite.All. PATCH channel documents
        # ChannelSettings.ReadWrite.All; Channel.Create / Channel.Delete.All do
        # not grant channel updates.
        "update_channel",
        # MISSING SCOPE: ChannelMember.Read.All. Listing channel members
        # documents ChannelMember.Read.All (higher: ChannelMember.ReadWrite.All,
        # Group.Read.All). TeamMember.ReadWrite.All covers team membership only.
        "list_channel_members",
        # The advanced trigger subscribes to a raw user-supplied resource path,
        # so the required permission is whatever that resource documents. Not
        # determinable from the operation alone.
        "on_change_notification",
    ),
)


# ===========================================================================
# OneLake  (automation-onelake)
# ===========================================================================
# Requests: storage.azure.com/user_impersonation,
# api.fabric.microsoft.com/OneLake.ReadWrite.All, offline_access.
#
# The split mirrors OneLakeNode.FABRIC_AUDIENCE_OPS: the node mints one token
# per audience and routes each request to the matching one, so a mismatch here
# would be an audience error, not a consent error.

_DFS = _onelake(
    ONELAKE_STORAGE,
    note="OneLake DFS/Blob/Table endpoints accept Storage-audience tokens only.",
)
_FABRIC = _onelake(ONELAKE_FABRIC)

_ONELAKE_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- DFS filesystem (onelake.dfs.fabric.microsoft.com) ------------------
    "list_paths": _DFS,
    "create_directory": _DFS,
    "create_file": _DFS,
    "append_file": _DFS,
    "flush_file": _DFS,
    "read_file": _DFS,
    "get_properties": _DFS,
    "set_properties": _DFS,
    "get_access_control": _DFS,
    "rename_path": _DFS,
    "delete_path": _DFS,
    "check_access": _DFS,
    "lease_path": _DFS,
    "on_new_file": _DFS,  # polls the DFS path listing
    # -- Blob endpoint (onelake.blob.fabric.microsoft.com) ------------------
    "list_blobs": _DFS,
    # -- Table endpoint (onelake.table.fabric.microsoft.com) ----------------
    "get_iceberg_config": _DFS,
    "list_iceberg_namespaces": _DFS,
    "get_iceberg_namespace": _DFS,
    "list_iceberg_tables": _DFS,
    "get_iceberg_table": _DFS,
    "list_delta_schemas": _DFS,
    "list_delta_tables": _DFS,
    "get_delta_table": _DFS,
    # -- Fabric Core: shortcuts --------------------------------------------
    "create_shortcut": _FABRIC,  # OneLake.ReadWrite.All
    "create_shortcuts_bulk": _FABRIC,  # OneLake.ReadWrite.All
    "get_shortcut": _FABRIC,  # OneLake.Read.All or OneLake.ReadWrite.All
    "list_shortcuts": _FABRIC,  # OneLake.Read.All or OneLake.ReadWrite.All
    "delete_shortcut": _FABRIC,  # OneLake.ReadWrite.All
    "reset_shortcut_cache": _FABRIC,  # OneLake.ReadWrite.All
    # -- Fabric Core: settings + data access roles -------------------------
    "get_settings": _FABRIC,  # OneLake.Read.All or OneLake.ReadWrite.All
    "list_data_access_roles": _FABRIC,  # OneLake.Read.All or ReadWrite.All
    "get_data_access_role": _FABRIC,  # OneLake.Read.All or ReadWrite.All
    "create_or_update_data_access_role": _FABRIC,  # OneLake.ReadWrite.All
    "delete_data_access_role": _FABRIC,  # OneLake.ReadWrite.All
}

ONELAKE_SCOPES = ScopeRegistry(
    provider="onelake",
    requirements=_ONELAKE_REQUIREMENTS,
)
