"""Dropbox → OAuth scope requirements (the family's shared notes are in content_storage.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.scopes.content_storage import _s


# ---------------------------------------------------------------------------
# Dropbox — scopes transcribed from Dropbox's own API spec: every route in
# https://github.com/dropbox/dropbox-api-spec carries a `scope = "..."`
# attribute, surfaced per method in the generated SDK
# (https://github.com/dropbox/dropbox-sdk-python `dropbox/base.py`).
# ---------------------------------------------------------------------------

_DROPBOX: dict[str, ScopeRequirement] = {
    # -- file content ----------------------------------------------------
    "upload_file": _s("files.content.write"),
    "upload_large_file_with_sessions": _s("files.content.write"),
    "create_folder": _s("files.content.write"),
    "delete_file_or_folder": _s("files.content.write"),
    "copy_file_or_folder": _s("files.content.write"),
    "move_file_or_folder": _s("files.content.write"),
    "restore_file_to_revision": _s("files.content.write"),
    "save_url_to_dropbox": _s("files.content.write"),
    "download_file": _s("files.content.read"),
    "download_folder_as_zip": _s("files.content.read"),
    "get_temporary_download_link": _s("files.content.read"),
    "get_file_thumbnail": _s("files.content.read"),
    # -- file metadata ---------------------------------------------------
    "list_folder_contents": _s("files.metadata.read"),
    "search_files_and_folders": _s("files.metadata.read"),
    "get_file_or_folder_metadata": _s("files.metadata.read"),
    "list_file_revisions": _s("files.metadata.read"),
    "add_custom_properties_to_file": _s("files.metadata.write"),
    "update_custom_properties": _s("files.metadata.write"),
    "remove_custom_properties": _s("files.metadata.write"),
    # -- sharing ---------------------------------------------------------
    "create_shared_link": _s("sharing.write"),
    "revoke_shared_link": _s("sharing.write"),
    "share_folder_with_members": _s("sharing.write"),
    "add_members_to_shared_folder": _s("sharing.write"),
    "remove_shared_folder_member": _s("sharing.write"),
    "update_shared_folder_member_access": _s("sharing.write"),
    "mount_shared_folder": _s("sharing.write"),
    "unmount_shared_folder": _s("sharing.write"),
    "unshare_folder": _s("sharing.write"),
    "share_file_with_members": _s("sharing.write"),
    "remove_file_member": _s("sharing.write"),
    "list_shared_links": _s("sharing.read"),
    "list_shared_folder_members": _s("sharing.read"),
    "get_shared_folder_metadata": _s("sharing.read"),
    "list_file_members": _s("sharing.read"),
    # -- file requests ---------------------------------------------------
    "create_file_request": _s("file_requests.write"),
    "update_file_request": _s("file_requests.write"),
    "delete_file_request": _s("file_requests.write"),
    "list_file_requests": _s("file_requests.read"),
    "get_file_request": _s("file_requests.read"),
    "count_file_requests": _s("file_requests.read"),
    # -- account ---------------------------------------------------------
    "get_account_info": _s("account_info.read"),
    "get_account_space_usage": _s("account_info.read"),
}

DROPBOX_SCOPES = ScopeRegistry(
    provider="dropbox",
    requirements=_DROPBOX,
)
