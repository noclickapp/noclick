"""
Auto-generated execution smoke tests for the repaired Discord handlers.

Each previously-dead handler is exercised end-to-end: construct its config from a
minimal sample, mock the HTTP layer (and media resolution), run execute(), and
assert the handler ran and returned its action. Verifies endpoint/payload code
paths don't reference non-existent config fields.
"""
import pytest
from unittest.mock import AsyncMock, patch

from nodes.core.media_resolver import ResolvedMedia
from nodes.discord_node import (
    DiscordNode,
    DiscordNodeConfig,
    DiscordBotTokenCredential,
    DiscordAddRoleToMemberConfig,
    DiscordAddThreadMemberConfig,
    DiscordBeginGuildPruneConfig,
    DiscordBulkDeleteMessagesConfig,
    DiscordCreateAutoModRuleConfig,
    DiscordCreateChannelConfig,
    DiscordCreateChannelInviteConfig,
    DiscordCreateRoleConfig,
    DiscordCreateScheduledEventConfig,
    DiscordCreateStageInstanceConfig,
    DiscordCrosspostMessageConfig,
    DiscordDeleteAllReactionsConfig,
    DiscordDeleteAllReactionsForEmojiConfig,
    DiscordDeleteAutoModRuleConfig,
    DiscordDeleteChannelConfig,
    DiscordDeleteGuildStickerConfig,
    DiscordDeleteInviteConfig,
    DiscordDeleteRoleConfig,
    DiscordDeleteScheduledEventConfig,
    DiscordDeleteStageInstanceConfig,
    DiscordEditChannelPermissionsConfig,
    DiscordEndPollConfig,
    DiscordGetAuditLogConfig,
    DiscordGetAutoModRuleConfig,
    DiscordGetChannelInvitesConfig,
    DiscordGetGuildBanConfig,
    DiscordGetGuildBansConfig,
    DiscordGetGuildInvitesConfig,
    DiscordGetGuildPreviewConfig,
    DiscordGetGuildPruneCountConfig,
    DiscordGetGuildStickerConfig,
    DiscordGetGuildVanityUrlConfig,
    DiscordGetInviteConfig,
    DiscordGetMessageConfig,
    DiscordGetPollAnswerVotersConfig,
    DiscordGetReactionsConfig,
    DiscordGetScheduledEventConfig,
    DiscordGetScheduledEventUsersConfig,
    DiscordGetStageInstanceConfig,
    DiscordJoinThreadConfig,
    DiscordLeaveThreadConfig,
    DiscordListActiveThreadsConfig,
    DiscordListAutoModRulesConfig,
    DiscordListGuildStickersConfig,
    DiscordListScheduledEventsConfig,
    DiscordListThreadMembersConfig,
    DiscordModifyAutoModRuleConfig,
    DiscordModifyChannelConfig,
    DiscordModifyGuildConfig,
    DiscordModifyGuildStickerConfig,
    DiscordModifyRoleConfig,
    DiscordModifyScheduledEventConfig,
    DiscordModifyStageInstanceConfig,
    DiscordRemoveRoleFromMemberConfig,
    DiscordRemoveThreadMemberConfig,
    DiscordStartThreadConfig,
    DiscordStartThreadFromMessageConfig,
    DiscordTriggerTypingConfig,
)


def _mock_node(config):
    nc = DiscordNodeConfig(config=config, credentials=DiscordBotTokenCredential(bot_token="mock"))
    return DiscordNode(
        node_id="n", node_type="automation-discord", node_data={},
        config=nc, sio=None, sid=None, workflow_id="w",
    )


_CASES = [
    (DiscordGetMessageConfig, {'channel_id': '123456789012345678', 'message_id': '987654321098765432'}, 'get_message_by_id', False, '_get_message'),
    (DiscordCrosspostMessageConfig, {'channel_id': '123456789012345678', 'message_id': '987654321098765432'}, 'crosspost_message_to_announcement_channel', False, '_crosspost_message'),
    (DiscordBulkDeleteMessagesConfig, {'channel_id': '123456789012345678', 'message_ids': ['987654321098765432', '987654321098765433']}, 'bulk_delete_channel_messages', False, '_bulk_delete_messages'),
    (DiscordGetReactionsConfig, {'channel_id': '123456789012345678', 'message_id': '987654321098765432', 'emoji': '👍'}, 'list_message_reaction_users', False, '_get_reactions'),
    (DiscordDeleteAllReactionsConfig, {'channel_id': '123456789012345678', 'message_id': '987654321098765432'}, 'delete_all_message_reactions', False, '_delete_all_reactions'),
    (DiscordDeleteAllReactionsForEmojiConfig, {'channel_id': '123456789012345678', 'message_id': '987654321098765432', 'emoji': '👍'}, 'delete_emoji_reactions_from_message', False, '_delete_all_reactions_for_emoji'),
    (DiscordTriggerTypingConfig, {'channel_id': '123456789012345678'}, 'show_typing_indicator_in_channel', False, '_trigger_typing'),
    (DiscordGetPollAnswerVotersConfig, {'channel_id': '123456789012345678', 'message_id': '987654321098765432', 'answer_id': 1}, 'list_poll_answer_voters', False, '_get_poll_answer_voters'),
    (DiscordEndPollConfig, {'channel_id': '123456789012345678', 'message_id': '987654321098765432'}, 'end_poll_immediately', False, '_end_poll'),
    (DiscordCreateChannelConfig, {'guild_id': '123456789012345678', 'name': 'general'}, 'create_channel_in_guild', False, '_create_channel'),
    (DiscordModifyChannelConfig, {'channel_id': '123456789012345678'}, 'update_channel_settings', False, '_modify_channel'),
    (DiscordDeleteChannelConfig, {'channel_id': '123456789012345678'}, 'delete_channel', False, '_delete_channel'),
    (DiscordEditChannelPermissionsConfig, {'channel_id': '123456789012345678', 'overwrite_id': '987654321098765432', 'type': 0}, 'edit_channel_permission_overwrites', False, '_edit_channel_permissions'),
    (DiscordStartThreadFromMessageConfig, {'channel_id': '123456789012345678', 'message_id': '234567890123456789', 'name': 'My Thread'}, 'start_thread_from_existing_message', False, '_start_thread_from_message'),
    (DiscordStartThreadConfig, {'channel_id': '123456789012345678', 'name': 'My Forum Thread'}, 'start_thread_in_forum_channel', False, '_start_thread'),
    (DiscordJoinThreadConfig, {'thread_id': '123456789012345678'}, 'join_thread', False, '_join_thread'),
    (DiscordLeaveThreadConfig, {'thread_id': '123456789012345678'}, 'leave_thread', False, '_leave_thread'),
    (DiscordAddThreadMemberConfig, {'thread_id': '123456789012345678', 'user_id': '234567890123456789'}, 'add_member_to_thread', False, '_add_thread_member'),
    (DiscordRemoveThreadMemberConfig, {'thread_id': '123456789012345678', 'user_id': '234567890123456789'}, 'remove_member_from_thread', False, '_remove_thread_member'),
    (DiscordListThreadMembersConfig, {'thread_id': '123456789012345678'}, 'list_thread_members', False, '_list_thread_members'),
    (DiscordListActiveThreadsConfig, {'guild_id': '123456789012345678'}, 'list_guild_active_threads', False, '_list_active_threads'),
    (DiscordCreateRoleConfig, {'guild_id': '123456789012345678', 'name': 'Moderators'}, 'create_role_in_guild', False, '_create_role'),
    (DiscordModifyRoleConfig, {'guild_id': '123456789012345678', 'role_id': '987654321098765432'}, 'update_guild_role', False, '_modify_role'),
    (DiscordDeleteRoleConfig, {'guild_id': '123456789012345678', 'role_id': '987654321098765432'}, 'delete_role_from_guild', False, '_delete_role'),
    (DiscordAddRoleToMemberConfig, {'guild_id': '123456789012345678', 'user_id': '111111111111111111', 'role_id': '987654321098765432'}, 'add_role_to_guild_member', False, '_add_role_to_member'),
    (DiscordRemoveRoleFromMemberConfig, {'guild_id': '123456789012345678', 'user_id': '111111111111111111', 'role_id': '987654321098765432'}, 'remove_role_from_guild_member', False, '_remove_role_from_member'),
    (DiscordModifyGuildConfig, {'guild_id': '123456789012345678'}, 'update_guild_settings', False, '_modify_guild'),
    (DiscordGetGuildPreviewConfig, {'guild_id': '123456789012345678'}, 'get_guild_preview', False, '_get_guild_preview'),
    (DiscordGetGuildVanityUrlConfig, {'guild_id': '123456789012345678'}, 'get_guild_vanity_url', False, '_get_guild_vanity_url'),
    (DiscordGetGuildPruneCountConfig, {'guild_id': '123456789012345678'}, 'get_guild_prune_count', False, '_get_guild_prune_count'),
    (DiscordBeginGuildPruneConfig, {'guild_id': '123456789012345678'}, 'begin_guild_prune_for_inactive_members', False, '_begin_guild_prune'),
    (DiscordGetGuildBansConfig, {'guild_id': '123456789012345678'}, 'list_guild_bans', False, '_get_guild_bans'),
    (DiscordGetGuildBanConfig, {'guild_id': '123456789012345678', 'user_id': '987654321098765432'}, 'get_guild_ban', False, '_get_guild_ban'),
    (DiscordGetAuditLogConfig, {'guild_id': '123456789012345678'}, 'get_guild_audit_log', False, '_get_audit_log'),
    (DiscordGetInviteConfig, {'invite_code': 'abc123'}, 'get_invite_info', False, '_get_invite'),
    (DiscordDeleteInviteConfig, {'invite_code': 'abc123'}, 'delete_invite', False, '_delete_invite'),
    (DiscordGetChannelInvitesConfig, {'channel_id': '123456789012345678'}, 'list_channel_invites', False, '_get_channel_invites'),
    (DiscordCreateChannelInviteConfig, {'channel_id': '123456789012345678'}, 'create_channel_invite', False, '_create_channel_invite'),
    (DiscordGetGuildInvitesConfig, {'guild_id': '123456789012345678'}, 'list_guild_invites', False, '_get_guild_invites'),
    (DiscordListGuildStickersConfig, {'guild_id': '123456789012345678'}, 'list_guild_stickers', False, '_list_guild_stickers'),
    (DiscordGetGuildStickerConfig, {'guild_id': '123456789012345678', 'sticker_id': '987654321098765432'}, 'get_sticker_from_guild', False, '_get_guild_sticker'),
    (DiscordModifyGuildStickerConfig, {'guild_id': '123456789012345678', 'sticker_id': '987654321098765432'}, 'update_guild_sticker', False, '_modify_guild_sticker'),
    (DiscordDeleteGuildStickerConfig, {'guild_id': '123456789012345678', 'sticker_id': '987654321098765432'}, 'delete_sticker_from_guild', False, '_delete_guild_sticker'),
    (DiscordListScheduledEventsConfig, {'guild_id': '123456789012345678'}, 'list_guild_scheduled_events', False, '_list_scheduled_events'),
    (DiscordGetScheduledEventConfig, {'guild_id': '123456789012345678', 'event_id': '987654321098765432'}, 'get_scheduled_event', False, '_get_scheduled_event'),
    (DiscordCreateScheduledEventConfig, {'guild_id': '123456789012345678', 'name': 'Community Meetup', 'scheduled_start_time': '2026-07-01T18:00:00.000Z', 'entity_type': 2}, 'create_scheduled_event', False, '_create_scheduled_event'),
    (DiscordModifyScheduledEventConfig, {'guild_id': '123456789012345678', 'event_id': '987654321098765432'}, 'update_scheduled_event', False, '_modify_scheduled_event'),
    (DiscordDeleteScheduledEventConfig, {'guild_id': '123456789012345678', 'event_id': '987654321098765432'}, 'delete_scheduled_event', False, '_delete_scheduled_event'),
    (DiscordGetScheduledEventUsersConfig, {'guild_id': '123456789012345678', 'event_id': '987654321098765432'}, 'list_scheduled_event_users', False, '_get_scheduled_event_users'),
    (DiscordListAutoModRulesConfig, {'guild_id': '123456789012345678'}, 'list_guild_auto_moderation_rules', False, '_list_auto_mod_rules'),
    (DiscordGetAutoModRuleConfig, {'guild_id': '123456789012345678', 'rule_id': '987654321098765432'}, 'get_auto_moderation_rule', False, '_get_auto_mod_rule'),
    (DiscordCreateAutoModRuleConfig, {'guild_id': '123456789012345678', 'name': 'No bad words', 'trigger_type': 1}, 'create_auto_moderation_rule', False, '_create_auto_mod_rule'),
    (DiscordModifyAutoModRuleConfig, {'guild_id': '123456789012345678', 'rule_id': '987654321098765432'}, 'update_auto_moderation_rule', False, '_modify_auto_mod_rule'),
    (DiscordDeleteAutoModRuleConfig, {'guild_id': '123456789012345678', 'rule_id': '987654321098765432'}, 'delete_auto_moderation_rule', False, '_delete_auto_mod_rule'),
    (DiscordCreateStageInstanceConfig, {'channel_id': '1234567890', 'topic': 'Town Hall'}, 'create_stage_instance', False, '_create_stage_instance'),
    (DiscordGetStageInstanceConfig, {'channel_id': '1234567890'}, 'get_stage_instance_for_channel', False, '_get_stage_instance'),
    (DiscordModifyStageInstanceConfig, {'channel_id': '1234567890'}, 'update_stage_instance', False, '_modify_stage_instance'),
    (DiscordDeleteStageInstanceConfig, {'channel_id': '1234567890'}, 'delete_stage_instance', False, '_delete_stage_instance'),
]


@pytest.mark.parametrize("config_cls,kwargs,expected_action,needs_media,handler", _CASES)
@pytest.mark.asyncio
async def test_repaired_handler_executes(config_cls, kwargs, expected_action, needs_media, handler):
    config = config_cls(**kwargs)
    node = _mock_node(config)
    resolved = ResolvedMedia(data=b"img", mime_type="image/png", filename="f.png")
    with patch.object(node, "_make_request", new_callable=AsyncMock) as mock_req, patch(
        "nodes.core.media_resolver.resolve_media_input",
        new=AsyncMock(return_value=resolved),
    ):
        mock_req.return_value = {}
        result = await node.execute({})
    assert isinstance(result, dict), f"{handler} returned non-dict"
    assert result.get("action") == expected_action, (
        f"{handler}: action {result.get('action')!r} != {expected_action!r}"
    )
    mock_req.assert_awaited()
