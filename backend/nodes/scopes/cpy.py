"""PeerTube bearer token scopes from the pinned official OpenAPI contract.

https://docs.joinpeertube.org/api-rest-reference/api.html
Only the identity endpoint declares a non-empty scope requirement. Role and
ownership checks remain the instance's responsibility.
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

CPY_SCOPES = ScopeRegistry(
    provider="cpy",
    requirements={
        "get_my_account": ScopeRequirement(scopes=("user",)),
        "list_videos": ScopeRequirement(scopes=()),
        "search_videos": ScopeRequirement(scopes=()),
        "get_video": ScopeRequirement(scopes=()),
        "update_video": ScopeRequirement(scopes=()),
        "delete_video": ScopeRequirement(scopes=()),
        "import_video": ScopeRequirement(scopes=()),
        "list_channels": ScopeRequirement(scopes=()),
        "get_channel": ScopeRequirement(scopes=()),
        "create_channel": ScopeRequirement(scopes=()),
        "update_channel": ScopeRequirement(scopes=()),
        "delete_channel": ScopeRequirement(scopes=()),
        "list_channel_videos": ScopeRequirement(scopes=()),
        "get_account": ScopeRequirement(scopes=()),
        "list_account_videos": ScopeRequirement(scopes=()),
        "list_playlists": ScopeRequirement(scopes=()),
        "create_playlist": ScopeRequirement(scopes=()),
        "list_playlist_videos": ScopeRequirement(scopes=()),
        "add_playlist_video": ScopeRequirement(scopes=()),
        "remove_playlist_video": ScopeRequirement(scopes=()),
        "list_captions": ScopeRequirement(scopes=()),
        "get_chapters": ScopeRequirement(scopes=()),
        "on_new_channel_video": ScopeRequirement(scopes=()),
        "on_new_channel": ScopeRequirement(scopes=()),
    },
)
