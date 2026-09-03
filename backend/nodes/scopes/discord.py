"""Discord operation → OAuth scope requirements.

Discord's REST API is not scope-gated the way most providers are. Every
operation this node executes is sent with an ``Authorization: Bot <token>``
header, and per Discord's docs bot users "have full access to most API routes
without using bearer tokens" — access is decided by the bot's **permission
bitfield** and its **privileged intents**, neither of which is an OAuth scope.
Do not confuse the two: the permission bitfield in the install URL is a
separate axis and has no place in this table.

The OAuth scope that matters is therefore the one that mints the bot in the
first place: ``bot``. Without it the install produces no bot and nothing here
can run. ``applications.commands`` is the one genuine per-surface scope — a
guild only has an app's commands if the app was authorized with it (it rides
along with ``bot`` by default) — so the command operations declare it
explicitly.

The user access token from the install (``identify``) is never used at execute
time, which is why ``list_user_connections`` cannot work: ``/users/@me/
connections`` is Bearer-only and needs the ``connections`` scope.
"""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement


def _s(*scopes: str) -> ScopeRequirement:
    return ScopeRequirement(scopes=scopes)


_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- Webhook execution (no credential) -----------------------------
    # Posting through a webhook URL carries its own token in the URL; the
    # node runs this operation without a credential at all.
    "execute_webhook_send_message": _s(),

    # -- Message -----------------------------------------------------
    "bulk_delete_channel_messages": _s("bot"),
    "crosspost_message_to_announcement_channel": _s("bot"),
    "delete_message_from_channel": _s("bot"),
    "edit_message_content": _s("bot"),
    "end_poll_immediately": _s("bot"),
    "get_message_by_id": _s("bot"),
    "list_channel_messages": _s("bot"),
    "list_pinned_messages_in_channel": _s("bot"),
    "pin_message_in_channel": _s("bot"),
    "send_embed_message_to_channel": _s("bot"),
    "send_message_to_channel": _s("bot"),
    "unpin_message_from_channel": _s("bot"),

    # -- Channel -----------------------------------------------------
    "create_channel_in_guild": _s("bot"),
    "delete_channel": _s("bot"),
    "edit_channel_permission_overwrites": _s("bot"),
    "get_channel_info": _s("bot"),
    "list_channel_invites": _s("bot"),
    "list_channel_webhooks": _s("bot"),
    "list_guild_channels": _s("bot"),
    "show_typing_indicator_in_channel": _s("bot"),
    "update_channel_settings": _s("bot"),

    # -- Guild -------------------------------------------------------
    "begin_guild_prune_for_inactive_members": _s("bot"),
    "create_guild_from_template": _s("bot"),
    "delete_guild_integration": _s("bot"),
    "get_guild_audit_log": _s("bot"),
    "get_guild_info": _s("bot"),
    "get_guild_onboarding_config": _s("bot"),
    "get_guild_preview": _s("bot"),
    "get_guild_prune_count": _s("bot"),
    "get_guild_vanity_url": _s("bot"),
    "get_guild_welcome_screen": _s("bot"),
    "get_guild_widget_settings": _s("bot"),
    "leave_guild": _s("bot"),
    "list_guild_integrations": _s("bot"),
    "list_guild_invites": _s("bot"),
    "list_user_guilds": _s("bot"),
    "update_guild_onboarding_config": _s("bot"),
    "update_guild_settings": _s("bot"),
    "update_guild_welcome_screen": _s("bot"),
    "update_guild_widget_settings": _s("bot"),

    # -- User --------------------------------------------------------
    "get_authenticated_user_info": _s("bot"),
    "list_current_user_guilds": _s("bot"),

    # -- Webhook -----------------------------------------------------
    "create_channel_webhook": _s("bot"),
    "delete_webhook": _s("bot"),
    "get_webhook_by_id": _s("bot"),
    "list_guild_webhooks": _s("bot"),
    "update_webhook_settings": _s("bot"),

    # -- Trigger -----------------------------------------------------
    "on_application_authorized": _s("bot"),
    "on_application_deauthorized": _s("bot"),
    "on_entitlement_create": _s("bot"),
    "on_entitlement_delete": _s("bot"),
    "on_entitlement_update": _s("bot"),
    "on_slash_command": _s("bot", "applications.commands"),
    # Channel messages arrive on the bot's Gateway session; the install's
    # ``bot`` scope is what puts the bot in the server. Reading message
    # content is a privileged INTENT toggled in the Developer Portal, not a
    # scope (see the module docstring).
    "on_message": _s("bot"),
    "on_mention": _s("bot"),

    # -- Reaction ----------------------------------------------------
    "add_reaction_to_message": _s("bot"),
    "delete_all_message_reactions": _s("bot"),
    "delete_emoji_reactions_from_message": _s("bot"),
    "list_message_reaction_users": _s("bot"),
    "remove_reaction_from_message": _s("bot"),

    # -- Member ------------------------------------------------------
    "ban_member_from_guild": _s("bot"),
    "get_guild_ban": _s("bot"),
    "get_guild_member_info": _s("bot"),
    "kick_member_from_guild": _s("bot"),
    "list_guild_bans": _s("bot"),
    "list_guild_members": _s("bot"),
    "unban_member_from_guild": _s("bot"),
    "update_guild_member_info": _s("bot"),

    # -- Role --------------------------------------------------------
    "add_role_to_guild_member": _s("bot"),
    "create_role_in_guild": _s("bot"),
    "delete_role_from_guild": _s("bot"),
    "list_guild_roles": _s("bot"),
    "remove_role_from_guild_member": _s("bot"),
    "update_guild_role": _s("bot"),

    # -- Thread ------------------------------------------------------
    "add_member_to_thread": _s("bot"),
    "join_thread": _s("bot"),
    "leave_thread": _s("bot"),
    "list_guild_active_threads": _s("bot"),
    "list_thread_members": _s("bot"),
    "remove_member_from_thread": _s("bot"),
    "start_thread_from_existing_message": _s("bot"),
    "start_thread_in_forum_channel": _s("bot"),

    # -- Invite ------------------------------------------------------
    "create_channel_invite": _s("bot"),
    "delete_invite": _s("bot"),
    "get_invite_info": _s("bot"),

    # -- Emoji -------------------------------------------------------
    "create_emoji_in_guild": _s("bot"),
    "delete_emoji_from_guild": _s("bot"),
    "get_emoji_from_guild": _s("bot"),
    "list_guild_emojis": _s("bot"),
    "update_guild_emoji": _s("bot"),

    # -- Sticker -----------------------------------------------------
    "delete_sticker_from_guild": _s("bot"),
    "get_sticker_from_guild": _s("bot"),
    "list_guild_stickers": _s("bot"),
    "update_guild_sticker": _s("bot"),

    # -- Scheduled Event ---------------------------------------------
    "create_scheduled_event": _s("bot"),
    "delete_scheduled_event": _s("bot"),
    "get_scheduled_event": _s("bot"),
    "list_guild_scheduled_events": _s("bot"),
    "list_scheduled_event_users": _s("bot"),
    "update_scheduled_event": _s("bot"),

    # -- Auto Moderation ---------------------------------------------
    "create_auto_moderation_rule": _s("bot"),
    "delete_auto_moderation_rule": _s("bot"),
    "get_auto_moderation_rule": _s("bot"),
    "list_guild_auto_moderation_rules": _s("bot"),
    "update_auto_moderation_rule": _s("bot"),

    # -- Stage Instance ----------------------------------------------
    "create_stage_instance": _s("bot"),
    "delete_stage_instance": _s("bot"),
    "get_stage_instance_for_channel": _s("bot"),
    "update_stage_instance": _s("bot"),

    # -- Voice -------------------------------------------------------
    "list_available_voice_regions": _s("bot"),
    "update_current_user_voice_state": _s("bot"),
    "update_user_voice_state": _s("bot"),

    # -- Poll --------------------------------------------------------
    "list_poll_answer_voters": _s("bot"),

    # -- Soundboard --------------------------------------------------
    "create_guild_soundboard_sound": _s("bot"),
    "delete_guild_soundboard_sound": _s("bot"),
    "get_guild_soundboard_sound": _s("bot"),
    "list_default_soundboard_sounds": _s("bot"),
    "list_guild_soundboard_sounds": _s("bot"),
    "play_soundboard_sound_in_voice_channel": _s("bot"),
    "update_guild_soundboard_sound": _s("bot"),

    # -- Guild Template ----------------------------------------------
    "create_guild_template": _s("bot"),
    "delete_guild_template": _s("bot"),
    "get_guild_template": _s("bot"),
    "list_guild_templates": _s("bot"),
    "sync_guild_template_with_state": _s("bot"),
    "update_guild_template": _s("bot"),

    # -- Direct Message ----------------------------------------------
    "create_direct_message_channel": _s("bot"),
    "create_group_direct_message_channel": _s("bot"),

    # -- Application Command -----------------------------------------
    "create_global_application_command": _s("bot", "applications.commands"),
    "create_guild_application_command": _s("bot", "applications.commands"),
    "delete_global_application_command": _s("bot", "applications.commands"),
    "delete_guild_application_command": _s("bot", "applications.commands"),
    "edit_global_application_command": _s("bot", "applications.commands"),
    "edit_guild_application_command": _s("bot", "applications.commands"),
    "get_global_application_command": _s("bot", "applications.commands"),
    "get_guild_application_command": _s("bot", "applications.commands"),
    "list_global_application_commands": _s("bot", "applications.commands"),
    "list_guild_application_commands": _s("bot", "applications.commands"),
}

DISCORD_SCOPES = ScopeRegistry(
    provider="discord",
    requirements=_REQUIREMENTS,
    unmapped=(
        # MISSING SCOPE: connections
        # GET /users/@me/connections — "Requires the `connections` OAuth2
        # scope" and is Bearer-only, so a bot token cannot satisfy it. The
        # node sends a bot token here, so this operation cannot work today.
        # Fixing it means requesting `connections` at connect (forces a
        # re-auth) AND routing the call through the install's user token.
        "list_user_connections",
        # Discord documents no authorization requirement for the monetization
        # endpoints (/applications/{id}/entitlements, /applications/{id}/skus)
        # — no scope, no token type. Declaring `bot` here would be a guess, so
        # they stay unmapped until Discord documents it.
        "consume_one_time_purchase_entitlement",
        "create_test_entitlement",
        "delete_test_entitlement",
        "list_application_entitlements",
        "list_application_skus",
    ),
)
