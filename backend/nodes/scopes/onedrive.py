"""OneDrive → OAuth scope requirements (Graph's shared notes are in microsoft.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.scopes.microsoft import GRAPH, _FILES_ALL


# ===========================================================================
# OneDrive  (automation-onedrive)
# ===========================================================================
# Requests: Files.ReadWrite.All, User.Read. Every driveItem method lists
# Files.ReadWrite.All among its accepted (higher-privileged) permissions, so
# the whole surface resolves to that one scope.

_ONEDRIVE_REQUIREMENTS: dict[str, ScopeRequirement] = {
    # -- drive / discovery -------------------------------------------------
    "get_drive_info": _FILES_ALL,  # Get drive
    "get_special_folder": _FILES_ALL,  # drive: Get special folder
    "list_recent_items": _FILES_ALL,  # drive: recent
    "list_shared_items": _FILES_ALL,  # drive: sharedWithMe
    "search_drive_items": _FILES_ALL,  # driveItem: search
    "track_drive_changes": _FILES_ALL,  # driveItem: delta
    # -- items: read -------------------------------------------------------
    "get_item_metadata": _FILES_ALL,  # Get driveItem
    "list_folder_contents": _FILES_ALL,  # driveItem: List children
    "download_item": _FILES_ALL,  # driveItem: Get content
    "get_item_download_stream": _FILES_ALL,  # Get driveItem + download URL
    "get_item_preview_url": _FILES_ALL,  # driveItem: preview
    "get_item_thumbnail": _FILES_ALL,  # driveItem: List thumbnails
    "list_item_thumbnails": _FILES_ALL,  # driveItem: List thumbnails
    "get_item_analytics": _FILES_ALL,  # Get itemAnalytics
    # -- items: write ------------------------------------------------------
    "create_folder": _FILES_ALL,  # driveItem: Create child
    "upload_file": _FILES_ALL,  # driveItem: Upload content
    "create_large_file_upload_session": _FILES_ALL,  # createUploadSession
    "update_item_metadata": _FILES_ALL,  # Update driveItem
    "move_item": _FILES_ALL,  # driveItem: Move
    "copy_item": _FILES_ALL,  # driveItem: copy
    "delete_item": _FILES_ALL,  # Delete driveItem
    "permanently_delete_item": _FILES_ALL,  # driveItem: permanentDelete
    # Restore from recycle bin documents Files.ReadWrite.All for personal
    # accounts and is "Not supported" for work or school delegated access.
    "restore_item_from_recycle_bin": ScopeRequirement(
        scopes=(GRAPH + "Files.ReadWrite.All",),
        note=(
            "driveItem: restore is documented for personal Microsoft accounts "
            "only; Microsoft lists it as not supported for work or school "
            "delegated access."
        ),
    ),
    # -- check in / out ----------------------------------------------------
    "check_out_file": _FILES_ALL,  # driveItem: checkout
    "check_in_file": _FILES_ALL,  # driveItem: checkin
    "discard_file_checkout": _FILES_ALL,  # driveItem: discardCheckout
    # -- versions ----------------------------------------------------------
    "list_file_versions": _FILES_ALL,  # driveItem: List versions
    "get_file_version": _FILES_ALL,  # Get driveItemVersion
    "restore_file_version": _FILES_ALL,  # driveItemVersion: restoreVersion
    # -- sharing / permissions ---------------------------------------------
    "create_sharing_link": _FILES_ALL,  # driveItem: createLink
    "send_sharing_invitation": _FILES_ALL,  # driveItem: invite
    "grant_item_permission": _FILES_ALL,  # driveItem: invite
    "list_item_permissions": _FILES_ALL,  # driveItem: List permissions
    "update_item_permission": _FILES_ALL,  # Update permission
    "delete_item_permission": _FILES_ALL,  # Delete permission
    # -- following ---------------------------------------------------------
    "follow_item": _FILES_ALL,  # driveItem: follow
    "unfollow_item": _FILES_ALL,  # driveItem: unfollow
}

ONEDRIVE_SCOPES = ScopeRegistry(
    provider="onedrive",
    requirements=_ONEDRIVE_REQUIREMENTS,
)
