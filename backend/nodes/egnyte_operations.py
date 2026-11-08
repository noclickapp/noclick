"""Egnyte Public API 1.3.6 operations; paths are relative to /pubapi.

Contract: https://developers.egnyte.com/integration/api/openapi/json
Documentation: https://us-partner-integrations.egnyte.com/integration/cfs/api-docs/
"""
EGNYTE_OPERATIONS = {
    "get_user_info": ("GET", "/v1/userinfo", None),
    "get_file_or_folder": ("GET", "/v1/fs/{path}", "Egnyte.filesystem"),
    "create_folder": ("POST", "/v1/fs/{path}", "Egnyte.filesystem"),
    "move_item": ("POST", "/v1/fs/{path}", "Egnyte.filesystem"),
    "copy_item": ("POST", "/v1/fs/{path}", "Egnyte.filesystem"),
    "lock_file": ("POST", "/v1/fs/{path}", "Egnyte.filesystem"),
    "unlock_file": ("POST", "/v1/fs/{path}", "Egnyte.filesystem"),
    "delete_item": ("DELETE", "/v1/fs/{path}", "Egnyte.filesystem"),
    "download_file": ("GET", "/v1/fs-content/{path}", "Egnyte.filesystem"),
    "search_files": ("GET", "/v1/search", "Egnyte.filesystem"),
    "list_links": ("GET", "/v1/links", "Egnyte.link"),
    "create_link": ("POST", "/v1/links", "Egnyte.link"),
    "get_link": ("GET", "/v1/links/{link_id}", "Egnyte.link"),
    "delete_link": ("DELETE", "/v1/links/{link_id}", "Egnyte.link"),
    "add_comment": ("POST", "/v1/notes", "Egnyte.filesystem"),
    "list_comments": ("GET", "/v1/notes", "Egnyte.filesystem"),
    "get_comment": ("GET", "/v1/notes/{comment_id}", "Egnyte.filesystem"),
    "delete_comment": ("DELETE", "/v1/notes/{comment_id}", "Egnyte.filesystem"),
    "get_events_cursor": ("GET", "/v1/events/cursor", "Egnyte.filesystem"),
    "list_events": ("GET", "/v1/events", "Egnyte.filesystem"),
}
