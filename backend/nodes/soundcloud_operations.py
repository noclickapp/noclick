"""One operation per SoundCloud public API endpoint.

Pinned contract 1.0.0: https://github.com/soundcloud/api
Current guide: https://developers.soundcloud.com/docs/api/guide
Lists return a single page; no continuation URLs are followed automatically.
"""

SOUNDCLOUD_OPERATIONS = {
    "get_current_user": {"method": "GET", "path": "/me", "query": ()},
    "list_my_tracks": {
        "method": "GET",
        "path": "/me/tracks",
        "query": ("limit", "linked_partitioning"),
    },
    "list_my_playlists": {
        "method": "GET",
        "path": "/me/playlists",
        "query": ("limit",),
    },
    "list_my_liked_tracks": {
        "method": "GET",
        "path": "/me/likes/tracks",
        "query": ("limit", "linked_partitioning"),
    },
    "list_my_followers": {
        "method": "GET",
        "path": "/me/followers",
        "query": ("limit",),
    },
    "list_my_followings": {
        "method": "GET",
        "path": "/me/followings",
        "query": ("limit", "offset"),
    },
    "list_following_tracks": {
        "method": "GET",
        "path": "/me/followings/tracks",
        "query": ("limit", "offset"),
    },
    "follow_user": {"method": "PUT", "path": "/me/followings/{user_id}", "query": ()},
    "unfollow_user": {
        "method": "DELETE",
        "path": "/me/followings/{user_id}",
        "query": (),
    },
    "create_playlist": {"method": "POST", "path": "/playlists", "query": ()},
    "update_playlist": {
        "method": "PUT",
        "path": "/playlists/{playlist_id}",
        "query": (),
    },
    "update_track": {"method": "PUT", "path": "/tracks/{track_id}", "query": ()},
    "delete_track": {"method": "DELETE", "path": "/tracks/{track_id}", "query": ()},
    "like_track": {"method": "POST", "path": "/likes/tracks/{track_id}", "query": ()},
    "unlike_track": {
        "method": "DELETE",
        "path": "/likes/tracks/{track_id}",
        "query": (),
    },
    "repost_track": {
        "method": "POST",
        "path": "/reposts/tracks/{track_id}",
        "query": (),
    },
    "unrepost_track": {
        "method": "DELETE",
        "path": "/reposts/tracks/{track_id}",
        "query": (),
    },
    "like_playlist": {
        "method": "POST",
        "path": "/likes/playlists/{playlist_id}",
        "query": (),
    },
    "unlike_playlist": {
        "method": "DELETE",
        "path": "/likes/playlists/{playlist_id}",
        "query": (),
    },
    "repost_playlist": {
        "method": "POST",
        "path": "/reposts/playlists/{playlist_id}",
        "query": (),
    },
    "unrepost_playlist": {
        "method": "DELETE",
        "path": "/reposts/playlists/{playlist_id}",
        "query": (),
    },
}
