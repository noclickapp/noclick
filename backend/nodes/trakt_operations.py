"""One published Trakt OpenAPI operation per action; no arbitrary routes."""
TRAKT_OPERATIONS = {
    "get_settings": {"method": "GET", "path": "/users/settings", "query": ()},
    "get_last_activities": {
        "method": "GET",
        "path": "/sync/last_activities",
        "query": (),
    },
    "search": {
        "method": "GET",
        "path": "/search/{type}",
        "query": ("query", "page", "limit"),
    },
    "get_movie": {"method": "GET", "path": "/movies/{id}", "query": ()},
    "get_show": {"method": "GET", "path": "/shows/{id}", "query": ()},
    "list_trending_movies": {
        "method": "GET",
        "path": "/movies/trending",
        "query": ("page", "limit"),
    },
    "list_movie_history": {
        "method": "GET",
        "path": "/users/{user_id}/history/movies",
        "query": ("page", "limit", "start_at", "end_at"),
    },
    "list_episode_history": {
        "method": "GET",
        "path": "/users/{user_id}/history/episodes",
        "query": ("page", "limit", "start_at", "end_at"),
    },
    "list_watchlist": {
        "method": "GET",
        "path": "/sync/watchlist/{type}/{sort_by}/{sort_how}",
        "query": ("page", "limit"),
    },
    "add_to_watchlist": {"method": "POST", "path": "/sync/watchlist", "query": ()},
    "remove_from_watchlist": {
        "method": "POST",
        "path": "/sync/watchlist/remove",
        "query": (),
    },
    "add_to_history": {"method": "POST", "path": "/sync/history", "query": ()},
    "remove_from_history": {
        "method": "POST",
        "path": "/sync/history/remove",
        "query": (),
    },
    "rate_item": {"method": "POST", "path": "/sync/ratings", "query": ()},
    "remove_rating": {"method": "POST", "path": "/sync/ratings/remove", "query": ()},
    "add_to_collection": {"method": "POST", "path": "/sync/collection", "query": ()},
    "remove_from_collection": {
        "method": "POST",
        "path": "/sync/collection/remove",
        "query": (),
    },
    "list_collection": {
        "method": "GET",
        "path": "/sync/collection/{type}",
        "query": ("page", "limit"),
    },
    "list_lists": {
        "method": "GET",
        "path": "/users/{user_id}/lists",
        "query": ("page", "limit"),
    },
    "create_list": {"method": "POST", "path": "/users/{user_id}/lists", "query": ()},
    "add_list_item": {
        "method": "POST",
        "path": "/users/{user_id}/lists/{list_id}/items",
        "query": (),
    },
    "remove_list_item": {
        "method": "POST",
        "path": "/users/{user_id}/lists/{list_id}/items/remove",
        "query": (),
    },
    "on_movie_watched": {
        "method": "GET",
        "path": "/users/{user_id}/history/movies",
        "query": ("page", "limit", "start_at"),
    },
    "on_episode_watched": {
        "method": "GET",
        "path": "/users/{user_id}/history/episodes",
        "query": ("page", "limit", "start_at"),
    },
    "on_watchlist_item_added": {
        "method": "GET",
        "path": "/sync/watchlist/{type}/{sort_by}/{sort_how}",
        "query": ("page", "limit"),
    },
}
