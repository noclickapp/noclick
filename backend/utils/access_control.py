"""
Access control utilities for resource sharing.
Provides functions to check user access to workflows and databases based on
ownership, direct shares, and organization membership.
"""

import logging
from typing import Optional, Literal, NamedTuple
from enum import Enum

logger = logging.getLogger(__name__)


class Permission(str, Enum):
    """Permission levels for shared resources."""

    NONE = "none"
    VIEW = "view"
    EDIT = "edit"
    OWNER = "owner"


class AccessResult(NamedTuple):
    """Result of an access check."""

    has_access: bool
    permission: Permission
    via: Optional[str] = None  # "owner", "direct_share", "org_share"


async def check_resource_access(
    conn,
    user_id: str,
    resource_type: Literal["workflow", "database"],
    resource_id: str,
) -> AccessResult:
    """
    Check if a user has access to a resource.

    Args:
        conn: Database connection (asyncpg)
        user_id: UUID of the user to check
        resource_type: Type of resource ("workflow" or "database")
        resource_id: UUID of the resource

    Returns:
        AccessResult with has_access, permission level, and how access was granted
    """
    # First check if user is the owner
    if resource_type == "workflow":
        owner_row = await conn.fetchrow(
            "SELECT owner_id FROM workflows WHERE id = $1 AND deleted_at IS NULL",
            resource_id,
        )
    elif resource_type == "database":
        owner_row = await conn.fetchrow(
            "SELECT owner_id FROM user_tables_metadata WHERE id = $1",
            resource_id,
        )
    else:
        return AccessResult(False, Permission.NONE)

    if not owner_row:
        # Resource doesn't exist
        return AccessResult(False, Permission.NONE)

    owner_id = str(owner_row["owner_id"])
    if owner_id == user_id:
        return AccessResult(True, Permission.OWNER, "owner")

    # Check for direct user share
    direct_share = await conn.fetchrow(
        """
        SELECT permission FROM resource_shares
        WHERE resource_type = $1
          AND resource_id = $2
          AND target_type = 'user'
          AND target_user_id = $3
        """,
        resource_type,
        resource_id,
        user_id,
    )

    if direct_share:
        perm = (
            Permission.EDIT if direct_share["permission"] == "edit" else Permission.VIEW
        )
        return AccessResult(True, perm, "direct_share")

    # Check for organization share (user must be a member)
    org_share = await conn.fetchrow(
        """
        SELECT rs.permission
        FROM resource_shares rs
        JOIN organization_members om ON rs.target_org_id = om.organization_id
        WHERE rs.resource_type = $1
          AND rs.resource_id = $2
          AND rs.target_type = 'organization'
          AND om.user_id = $3
        """,
        resource_type,
        resource_id,
        user_id,
    )

    if org_share:
        perm = Permission.EDIT if org_share["permission"] == "edit" else Permission.VIEW
        return AccessResult(True, perm, "org_share")

    # Check for folder-level share (workflow belongs to a folder — or any ancestor — shared with user)
    if resource_type == "workflow":
        folder_user_share = await conn.fetchrow(
            """
            SELECT rs.permission
            FROM resource_shares rs
            JOIN workflow_folders shared_folder ON shared_folder.id = rs.resource_id
            JOIN workflows w ON w.id = $1
            JOIN workflow_folders wf ON wf.id = w.folder_id
            WHERE rs.resource_type = 'workflow_folder'
              AND rs.target_type = 'user'
              AND rs.target_user_id = $2
              AND (wf.id = shared_folder.id OR wf.path LIKE shared_folder.path || '%')
            LIMIT 1
            """,
            resource_id,
            user_id,
        )

        if folder_user_share:
            perm = (
                Permission.EDIT
                if folder_user_share["permission"] == "edit"
                else Permission.VIEW
            )
            return AccessResult(True, perm, "folder_share")

        folder_org_share = await conn.fetchrow(
            """
            SELECT rs.permission
            FROM resource_shares rs
            JOIN workflow_folders shared_folder ON shared_folder.id = rs.resource_id
            JOIN workflows w ON w.id = $1
            JOIN workflow_folders wf ON wf.id = w.folder_id
            JOIN organization_members om ON rs.target_org_id = om.organization_id
            WHERE rs.resource_type = 'workflow_folder'
              AND rs.target_type = 'organization'
              AND om.user_id = $2
              AND (wf.id = shared_folder.id OR wf.path LIKE shared_folder.path || '%')
            LIMIT 1
            """,
            resource_id,
            user_id,
        )

        if folder_org_share:
            perm = (
                Permission.EDIT
                if folder_org_share["permission"] == "edit"
                else Permission.VIEW
            )
            return AccessResult(True, perm, "org_folder_share")

    return AccessResult(False, Permission.NONE)


async def has_view_access(
    conn,
    user_id: str,
    resource_type: Literal["workflow", "database"],
    resource_id: str,
) -> bool:
    """Quick check for view access (includes edit and owner)."""
    result = await check_resource_access(conn, user_id, resource_type, resource_id)
    return result.has_access


async def has_edit_access(
    conn,
    user_id: str,
    resource_type: Literal["workflow", "database"],
    resource_id: str,
) -> bool:
    """Quick check for edit access (includes owner)."""
    result = await check_resource_access(conn, user_id, resource_type, resource_id)
    return result.permission in (Permission.EDIT, Permission.OWNER)


async def is_owner(
    conn,
    user_id: str,
    resource_type: Literal["workflow", "database"],
    resource_id: str,
) -> bool:
    """Check if user is the owner of a resource."""
    result = await check_resource_access(conn, user_id, resource_type, resource_id)
    return result.permission == Permission.OWNER


async def get_accessible_resources(
    conn,
    user_id: str,
    resource_type: Literal["workflow", "database"],
    include_owned: bool = True,
) -> list[dict]:
    """
    Get all resources a user can access (owned + shared).

    Returns list of dicts with resource_id, permission, and via.
    """
    resources = []

    if include_owned:
        # Get owned resources
        if resource_type == "workflow":
            owned_rows = await conn.fetch(
                "SELECT id FROM workflows WHERE owner_id = $1", user_id
            )
        else:
            owned_rows = await conn.fetch(
                "SELECT id FROM user_tables_metadata WHERE owner_id = $1", user_id
            )

        for row in owned_rows:
            resources.append(
                {
                    "resource_id": str(row["id"]),
                    "permission": Permission.OWNER.value,
                    "via": "owner",
                }
            )

    # Get directly shared resources
    direct_shares = await conn.fetch(
        """
        SELECT resource_id, permission FROM resource_shares
        WHERE resource_type = $1
          AND target_type = 'user'
          AND target_user_id = $2
        """,
        resource_type,
        user_id,
    )

    for row in direct_shares:
        resources.append(
            {
                "resource_id": str(row["resource_id"]),
                "permission": row["permission"],
                "via": "direct_share",
            }
        )

    # Get org-shared resources
    org_shares = await conn.fetch(
        """
        SELECT DISTINCT rs.resource_id, rs.permission
        FROM resource_shares rs
        JOIN organization_members om ON rs.target_org_id = om.organization_id
        WHERE rs.resource_type = $1
          AND rs.target_type = 'organization'
          AND om.user_id = $2
        """,
        resource_type,
        user_id,
    )

    for row in org_shares:
        resources.append(
            {
                "resource_id": str(row["resource_id"]),
                "permission": row["permission"],
                "via": "org_share",
            }
        )

    # Get folder-shared workflows (a workflow whose folder — or any ancestor — is
    # shared with the user directly or via their org). Workflow-only; mirrors the
    # folder branch of check_resource_access so listing matches what's accessible.
    if resource_type == "workflow":
        folder_user_shares = await conn.fetch(
            """
            SELECT DISTINCT w.id AS resource_id, rs.permission
            FROM resource_shares rs
            JOIN workflow_folders shared_folder ON shared_folder.id = rs.resource_id
            JOIN workflow_folders wf
              ON (wf.id = shared_folder.id OR wf.path LIKE shared_folder.path || '%')
            JOIN workflows w ON w.folder_id = wf.id
            WHERE rs.resource_type = 'workflow_folder'
              AND rs.target_type = 'user'
              AND rs.target_user_id = $1
            """,
            user_id,
        )
        for row in folder_user_shares:
            resources.append(
                {
                    "resource_id": str(row["resource_id"]),
                    "permission": row["permission"],
                    "via": "folder_share",
                }
            )

        folder_org_shares = await conn.fetch(
            """
            SELECT DISTINCT w.id AS resource_id, rs.permission
            FROM resource_shares rs
            JOIN workflow_folders shared_folder ON shared_folder.id = rs.resource_id
            JOIN workflow_folders wf
              ON (wf.id = shared_folder.id OR wf.path LIKE shared_folder.path || '%')
            JOIN workflows w ON w.folder_id = wf.id
            JOIN organization_members om ON rs.target_org_id = om.organization_id
            WHERE rs.resource_type = 'workflow_folder'
              AND rs.target_type = 'organization'
              AND om.user_id = $1
            """,
            user_id,
        )
        for row in folder_org_shares:
            resources.append(
                {
                    "resource_id": str(row["resource_id"]),
                    "permission": row["permission"],
                    "via": "org_folder_share",
                }
            )

    return resources
