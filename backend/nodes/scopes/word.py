"""Microsoft Word → OAuth scope requirements (Graph's shared notes are in microsoft.py)."""

from __future__ import annotations

from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.scopes.microsoft import _FILES_ALL


# ===========================================================================
# Word  (automation-word)
# ===========================================================================
# Requests: Files.ReadWrite.All, User.Read. Word is a driveItem client — every
# operation is a /me/drive call, so it maps exactly like OneDrive.

_WORD_REQUIREMENTS: dict[str, ScopeRequirement] = {
    "list_onedrive_documents": _FILES_ALL,  # driveItem: List children
    "search_onedrive_documents": _FILES_ALL,  # driveItem: search
    "fetch_document_metadata": _FILES_ALL,  # Get driveItem
    "create_blank_document": _FILES_ALL,  # driveItem: Upload content
    "upload_word_document": _FILES_ALL,  # driveItem: Upload content
    "copy_word_document": _FILES_ALL,  # driveItem: copy
    "move_document_to_folder": _FILES_ALL,  # Update driveItem (parentReference)
    "rename_word_document": _FILES_ALL,  # Update driveItem
    "delete_word_document": _FILES_ALL,  # Delete / permanentDelete driveItem
    "download_document_content": _FILES_ALL,  # driveItem: Get content
    "convert_document_to_pdf": _FILES_ALL,  # Get content (format=pdf)
    "convert_document_to_html": _FILES_ALL,  # Get content (format=html)
    "fetch_document_preview_link": _FILES_ALL,  # driveItem: preview
    "fetch_document_thumbnail": _FILES_ALL,  # driveItem: List thumbnails
    "create_document_sharing_link": _FILES_ALL,  # driveItem: createLink
    "share_document_with_user": _FILES_ALL,  # driveItem: invite
    "list_document_permissions": _FILES_ALL,  # driveItem: List permissions
    "update_document_permission_level": _FILES_ALL,  # Update permission
    "remove_document_sharing_permission": _FILES_ALL,  # Delete permission
    "list_document_version_history": _FILES_ALL,  # driveItem: List versions
    "fetch_document_version": _FILES_ALL,  # driveItemVersion: Get content
    "restore_document_to_previous_version": _FILES_ALL,  # restoreVersion
}

WORD_SCOPES = ScopeRegistry(
    provider="word",
    requirements=_WORD_REQUIREMENTS,
)
