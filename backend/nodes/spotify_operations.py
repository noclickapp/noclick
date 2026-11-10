"""Spotify Web API operations, pinned to the provider's OpenAPI 1.0.0.

https://developer.spotify.com/reference/web-api/open-api-schema.yaml
Each public operation makes one request to exactly one contract operation.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    contract_id: str
    category: str
    required: tuple[str, ...] = ()
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()


PLAYLIST_WRITE = ("playlist-modify-public", "playlist-modify-private")
LIBRARY_WRITE = ("user-library-modify", "user-follow-modify", "playlist-modify-public")
PAGE = ("limit", "offset")
OPERATIONS = {
    "get_profile": Operation("GET", "/me", "get-current-users-profile", "Account", scopes=("user-read-private", "user-read-email")),
    "search": Operation("GET", "/search", "search", "Catalog", ("q", "type"), ("q", "type", "market", *PAGE)),
    "get_track": Operation("GET", "/tracks/{track_id}", "get-track", "Catalog", ("track_id",), ("market",)),
    "get_artist": Operation("GET", "/artists/{artist_id}", "get-an-artist", "Catalog", ("artist_id",)),
    "list_playlists": Operation("GET", "/me/playlists", "get-a-list-of-current-users-playlists", "Playlists", query=PAGE, scopes=("playlist-read-private",)),
    "get_playlist": Operation("GET", "/playlists/{playlist_id}", "get-playlist", "Playlists", ("playlist_id",), ("market",)),
    "list_playlist_items": Operation("GET", "/playlists/{playlist_id}/items", "get-playlists-items", "Playlists", ("playlist_id",), ("market", *PAGE), scopes=("playlist-read-private",)),
    "create_playlist": Operation("POST", "/me/playlists", "create-playlist", "Playlists", ("name",), body=("name", "description", "public", "collaborative"), scopes=PLAYLIST_WRITE),
    "update_playlist": Operation("PUT", "/playlists/{playlist_id}", "change-playlist-details", "Playlists", ("playlist_id",), body=("name", "description", "public", "collaborative"), scopes=PLAYLIST_WRITE),
    "add_playlist_items": Operation("POST", "/playlists/{playlist_id}/items", "add-items-to-playlist", "Playlists", ("playlist_id", "uris"), body=("uris", "position"), scopes=PLAYLIST_WRITE),
    "replace_playlist_items": Operation("PUT", "/playlists/{playlist_id}/items", "reorder-or-replace-playlists-items", "Playlists", ("playlist_id", "uris"), body=("uris",), scopes=PLAYLIST_WRITE),
    "remove_playlist_items": Operation("DELETE", "/playlists/{playlist_id}/items", "remove-items-playlist", "Playlists", ("playlist_id", "uris"), body=("uris", "snapshot_id"), scopes=PLAYLIST_WRITE),
    "list_saved_tracks": Operation("GET", "/me/tracks", "get-users-saved-tracks", "Library", query=("market", *PAGE), scopes=("user-library-read",)),
    "save_library_items": Operation("PUT", "/me/library", "save-library-items", "Library", ("uris",), ("uris",), scopes=LIBRARY_WRITE),
    "remove_library_items": Operation("DELETE", "/me/library", "remove-library-items", "Library", ("uris",), ("uris",), scopes=LIBRARY_WRITE),
    "check_library_items": Operation("GET", "/me/library/contains", "check-library-contains", "Library", ("uris",), ("uris",), scopes=("user-library-read", "user-follow-read", "playlist-read-private")),
    "get_recently_played": Operation("GET", "/me/player/recently-played", "get-recently-played", "History", query=("limit", "after", "before"), scopes=("user-read-recently-played",)),
    "get_playback": Operation("GET", "/me/player", "get-information-about-the-users-current-playback", "Player", query=("market",), scopes=("user-read-playback-state",)),
    "list_devices": Operation("GET", "/me/player/devices", "get-a-users-available-devices", "Player", scopes=("user-read-playback-state",)),
    "start_playback": Operation("PUT", "/me/player/play", "start-a-users-playback", "Player", query=("device_id",), body=("context_uri", "uris", "position_ms"), scopes=("user-modify-playback-state",)),
    "pause_playback": Operation("PUT", "/me/player/pause", "pause-a-users-playback", "Player", query=("device_id",), scopes=("user-modify-playback-state",)),
    "skip_next": Operation("POST", "/me/player/next", "skip-users-playback-to-next-track", "Player", query=("device_id",), scopes=("user-modify-playback-state",)),
    "add_to_queue": Operation("POST", "/me/player/queue", "add-to-queue", "Player", ("uri",), ("uri", "device_id"), scopes=("user-modify-playback-state",)),
    "get_queue": Operation("GET", "/me/player/queue", "get-queue", "Player", scopes=("user-read-currently-playing", "user-read-playback-state")),
}
