"""Scopes from Spotify's per-operation OpenAPI security declarations.

https://developer.spotify.com/documentation/web-api/concepts/scopes
https://developer.spotify.com/reference/web-api/open-api-schema.yaml
"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.spotify_operations import OPERATIONS

SPOTIFY_SCOPES = ScopeRegistry(
    provider="spotify",
    requirements={
        **{name: ScopeRequirement(scopes=op.scopes) for name, op in OPERATIONS.items()},
        "on_track_played": ScopeRequirement(scopes=("user-read-recently-played",)),
    },
)
