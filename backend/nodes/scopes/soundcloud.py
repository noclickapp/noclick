"""SoundCloud grants account access without granular scope strings.

The current authorization example supplies no scope parameter:
https://developers.soundcloud.com/docs/api/guide#authentication
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.soundcloud_operations import SOUNDCLOUD_OPERATIONS

SOUNDCLOUD_SCOPES = ScopeRegistry(
    provider="soundcloud",
    requirements={operation: ScopeRequirement() for operation in SOUNDCLOUD_OPERATIONS},
)
