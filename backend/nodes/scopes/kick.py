"""Kick scopes: https://docs.kick.com/scopes/scopes and the pinned endpoint security declarations."""
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement

KICK_SCOPES = ScopeRegistry(
    provider="kick",
    enforcement=Enforcement.STRICT,
    requirements={
        'get_users': ScopeRequirement(scopes=('user:read',)),
        'search_categories': ScopeRequirement(scopes=()),
        'get_category': ScopeRequirement(scopes=()),
        'get_channels': ScopeRequirement(scopes=('channel:read',)),
        'update_channel': ScopeRequirement(scopes=('channel:write',)),
        'list_rewards': ScopeRequirement(scopes=('channel:rewards:read',)),
        'create_reward': ScopeRequirement(scopes=('channel:rewards:write',)),
        'update_reward': ScopeRequirement(scopes=('channel:rewards:write',)),
        'delete_reward': ScopeRequirement(scopes=('channel:rewards:write',)),
        'list_redemptions': ScopeRequirement(scopes=('channel:rewards:read',)),
        'accept_redemptions': ScopeRequirement(scopes=('channel:rewards:write',)),
        'reject_redemptions': ScopeRequirement(scopes=('channel:rewards:write',)),
        'send_message': ScopeRequirement(scopes=('chat:write',)),
        'delete_message': ScopeRequirement(scopes=('moderation:chat_message:manage',)),
        'list_livestreams': ScopeRequirement(scopes=()),
        'get_livestream_stats': ScopeRequirement(scopes=()),
        'list_user_livestreams': ScopeRequirement(scopes=()),
        'ban_user': ScopeRequirement(scopes=('moderation:ban',)),
        'unban_user': ScopeRequirement(scopes=('moderation:ban',)),
        'get_leaderboard': ScopeRequirement(scopes=('kicks:read',)),
    },
)
