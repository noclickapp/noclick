"""
Folder handler for managing workflow folder organization.
Handles folder creation, listing, moving, and deletion with hierarchical structure.
"""

import logging
from typing import Dict, Callable, Optional, List
from utils.database_pool import DatabasePoolMixin
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from utils.access_control import check_resource_access, Permission
from repositories.organization import OrgRepo
from wss.sender.responses import (
    FolderInfo,
    FolderListResponse,
    FolderGetResponse,
    FolderCreateResponse,
    FolderUpdateResponse,
    FolderDeleteResponse,
    FolderTreeResponse,
    FolderPathResponse,
)
from wss.receiver.client_events import (
    FolderCreateRequest,
    FolderListRequest,
    FolderGetRequest,
    FolderUpdateRequest,
    FolderDeleteRequest,
    FolderGetTreeRequest,
    FolderGetPathRequest,
    WorkflowMoveToFolderRequest,
    MCPFolderGetTreeRequest,
)

logger = logging.getLogger(__name__)


# Class-level singleton for the module-level shim below — never uses its pool
# attribute (get_primary_org_id takes an outer conn), so passing None is safe.
_ORG_REPO_STATELESS = OrgRepo(None)


async def get_user_org_context(conn, user_id: str) -> Optional[str]:
    """
    Get the user's current organization context.

    Returns:
        The organization_id if user has an active org context (is_primary=true),
        or None if user is in personal context.

    Thin shim over ``OrgRepo.get_primary_org_id`` — kept as a module-level
    function because other handlers/tests import it directly.
    """
    return await _ORG_REPO_STATELESS.get_primary_org_id(conn, user_id)


class FolderHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for workflow folder operations with hierarchical organization"""

    def __init__(self, sio):
        super().__init__(sio)

    async def _get_user_id(self, sid: str, request) -> Optional[str]:
        """
        Get user_id from request (injected by MCP transport) or session.

        MCP transport injects _user_id for authenticated requests. For non-MCP
        requests (direct frontend socket events), falls back to session.
        """
        if hasattr(request, '_user_id') and request._user_id:
            return request._user_id
        try:
            session = await self.sio.get_session(sid)
            return session.get('user_id')
        except Exception as e:
            logger.warning(f"Failed to get session for sid {sid}: {e}")
            return None

    def get_events(self) -> Dict[str, Callable]:
        """Register folder operation events (frontend + MCP)"""
        return {
            # Frontend events
            "workflow_folder:create": self.create_folder,
            "workflow_folder:list": self.list_folders,
            "workflow_folder:get": self.get_folder,
            "workflow_folder:update": self.update_folder,
            "workflow_folder:delete": self.delete_folder,
            "workflow_folder:get_tree": self.get_folder_tree,
            "workflow_folder:get_path": self.get_folder_path,
            "workflow_folder:move_workflow": self.move_workflow_to_folder,
            # MCP events (same handlers, different event names for MCP adapter discovery)
            "workflow:mcp:get_folder_tree": self.get_folder_tree,
        }

    async def setup_user(self, sid: str) -> None:
        """Initialize database connection pool on user setup - non-blocking"""
        _ = sid  # Suppress unused parameter warning

    async def create_folder(self, sid: str, request) -> None:
        """Create a new folder"""
        try:
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Get user's current organization context
                org_id = await repo.get_primary_org_id(conn, user_id)

                # Validate parent folder access if parent_folder_id is provided
                if request.parent_folder_id:
                    if not await repo.can_access_folder(conn, user_id, request.parent_folder_id):
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id,
                            data={},
                            error="Invalid parent folder or access denied"
                        ))
                        return

                    # Validate parent folder is in same organization context
                    parent_row = await repo.get_folder_organization_row(conn, request.parent_folder_id)
                    if parent_row:
                        parent_org_id = str(parent_row['organization_id']) if parent_row['organization_id'] else None
                        if parent_org_id != org_id:
                            await send_event(self.sio, sid, ResponseEvent(
                                request_id=request.request_id,
                                data={},
                                error="Parent folder must be in the same organization context"
                            ))
                            return

                # Insert folder into database
                # Path and depth are automatically calculated by trigger
                row = await repo.insert_folder(
                    conn,
                    owner_id=user_id,
                    organization_id=org_id,
                    name=request.name,
                    description=request.description or '',
                    parent_folder_id=request.parent_folder_id,
                )

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Failed to create folder"
                    ))
                    return

                # Convert to FolderInfo
                folder = FolderInfo(
                    id=str(row['id']),
                    name=row['name'],
                    description=row['description'] or '',
                    parent_folder_id=str(row['parent_folder_id']) if row['parent_folder_id'] else None,
                    path=row['path'],
                    depth=row['depth'],
                    created_at=row['created_at'].isoformat() if row.get('created_at') else '',
                    updated_at=row['updated_at'].isoformat() if row.get('updated_at') else '',
                    is_owner=True,
                    workflow_count=0  # Empty folder
                )

                # Send success response
                response = FolderCreateResponse(
                    success=True,
                    folder=folder,
                    message="Folder created successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"Error creating folder: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def list_folders(self, sid: str, request) -> None:
        """List folders (optionally filtered by parent_folder_id)"""
        try:
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Get user's current organization context
                org_id = await repo.get_primary_org_id(conn, user_id)

                # Repo owns the two SQL variants (org context vs personal +
                # shared) and the parent_folder_id filter composition.
                rows = await repo.list_folders(
                    conn,
                    user_id=user_id,
                    org_id=org_id,
                    parent_folder_id=request.parent_folder_id,
                )

                # Convert to FolderInfo objects
                folders = []
                for row in rows:
                    is_owner = str(row['owner_id']) == user_id
                    folders.append(FolderInfo(
                        id=str(row['id']),
                        name=row['name'],
                        description=row['description'] or '',
                        parent_folder_id=str(row['parent_folder_id']) if row['parent_folder_id'] else None,
                        path=row['path'],
                        depth=row['depth'],
                        created_at=row['created_at'].isoformat() if row.get('created_at') else '',
                        updated_at=row['updated_at'].isoformat() if row.get('updated_at') else '',
                        is_owner=is_owner,
                        owner_name=row.get('owner_display_name') if not is_owner else None,
                        workflow_count=row['workflow_count'] or 0
                    ))

                # Send response
                response = FolderListResponse(folders=folders)
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"Error listing folders: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def get_folder(self, sid: str, request) -> None:
        """Get a specific folder by ID"""
        try:
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Check folder access
                if not await repo.can_access_folder(conn, user_id, request.folder_id):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Folder not found or access denied"
                    ))
                    return

                # Get folder details
                row = await repo.get_folder_with_workflow_count(conn, request.folder_id)

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Folder not found"
                    ))
                    return

                is_owner = str(row['owner_id']) == user_id
                folder = FolderInfo(
                    id=str(row['id']),
                    name=row['name'],
                    description=row['description'] or '',
                    parent_folder_id=str(row['parent_folder_id']) if row['parent_folder_id'] else None,
                    path=row['path'],
                    depth=row['depth'],
                    created_at=row['created_at'].isoformat() if row.get('created_at') else '',
                    updated_at=row['updated_at'].isoformat() if row.get('updated_at') else '',
                    is_owner=is_owner,
                    workflow_count=row['workflow_count'] or 0
                )

                # Send response
                response = FolderGetResponse(folder=folder)
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"Error getting folder: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def update_folder(self, sid: str, request) -> None:
        """Update folder (rename or move)"""
        try:
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify folder ownership (only owner can update)
                row = await repo.get_folder_owner(conn, request.folder_id)

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Folder not found"
                    ))
                    return

                if str(row['owner_id']) != user_id:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Only folder owner can update folder"
                    ))
                    return

                # Collect allowlisted updates — repo enforces the column allowlist
                updates_payload: dict = {}
                if request.name is not None:
                    updates_payload['name'] = request.name
                if request.description is not None:
                    updates_payload['description'] = request.description
                if "parent_folder_id" in request.model_fields_set:
                    # Explicitly provided — None means move to root, otherwise move to new parent
                    if request.parent_folder_id is not None:
                        # Validate new parent access
                        if not await repo.can_access_folder(conn, user_id, request.parent_folder_id):
                            await send_event(self.sio, sid, ResponseEvent(
                                request_id=request.request_id,
                                data={},
                                error="Invalid parent folder or access denied"
                            ))
                            return
                    updates_payload['parent_folder_id'] = request.parent_folder_id

                if not updates_payload:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="No updates provided"
                    ))
                    return

                # Execute update (trigger recomputes path/depth on parent change)
                updated_row = await repo.update_folder(conn, request.folder_id, updates_payload)

                if not updated_row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Failed to update folder"
                    ))
                    return

                folder = FolderInfo(
                    id=str(updated_row['id']),
                    name=updated_row['name'],
                    description=updated_row['description'] or '',
                    parent_folder_id=str(updated_row['parent_folder_id']) if updated_row['parent_folder_id'] else None,
                    path=updated_row['path'],
                    depth=updated_row['depth'],
                    created_at=updated_row['created_at'].isoformat() if updated_row.get('created_at') else '',
                    updated_at=updated_row['updated_at'].isoformat() if updated_row.get('updated_at') else '',
                    is_owner=True,
                    workflow_count=0
                )

                # Send success response
                response = FolderUpdateResponse(
                    success=True,
                    folder=folder,
                    message="Folder updated successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"Error updating folder: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def delete_folder(self, sid: str, request) -> None:
        """Delete folder (workflows move to parent by default)"""
        try:
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify folder ownership
                row = await repo.get_folder_owner_and_parent(conn, request.folder_id)

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Folder not found"
                    ))
                    return

                if str(row['owner_id']) != user_id:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Only folder owner can delete folder"
                    ))
                    return

                # Move workflows to parent folder (or root if no parent).
                # ON DELETE SET NULL would handle this, but explicit is safer
                # for the DEFAULT-to-root case.
                await repo.hoist_workflows_to_parent(
                    conn, request.folder_id, row['parent_folder_id']
                )

                # Delete folder (CASCADE will delete child folders)
                await repo.delete_folder(conn, request.folder_id)

                # Send success response
                response = FolderDeleteResponse(
                    success=True,
                    message="Folder deleted successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"Error deleting folder: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def get_folder_tree(self, sid: str, request) -> None:
        """Get complete folder tree for sidebar"""
        try:
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Scope from the request (browser passes it explicitly), falling
                # back to the active context for non-browser callers. Explicit
                # scoping is immune to the is_primary org-switch race.
                org_id = await repo.resolve_scope_org_id(conn, user_id, getattr(request, 'scope_org_id', None))

                # Repo owns the org-context vs personal-shared SQL split.
                rows = await repo.get_folder_tree_rows(
                    conn, user_id=user_id, org_id=org_id
                )

                # Build tree structure
                folders_by_id = {}
                root_folders = []

                for row in rows:
                    is_owner = str(row['owner_id']) == user_id
                    folder_info = FolderInfo(
                        id=str(row['id']),
                        name=row['name'],
                        description=row['description'] or '',
                        parent_folder_id=str(row['parent_folder_id']) if row['parent_folder_id'] else None,
                        path=row['path'],
                        depth=row['depth'],
                        created_at=row['created_at'].isoformat() if row.get('created_at') else '',
                        updated_at=row['updated_at'].isoformat() if row.get('updated_at') else '',
                        is_owner=is_owner,
                        workflow_count=row['workflow_count'] or 0,
                        children=[]
                    )
                    folders_by_id[str(row['id'])] = folder_info

                # Build parent-child relationships
                # Folders whose parent is not in the result set appear as root-level items
                # (e.g., shared folders whose parent the user doesn't have access to)
                for folder_id, folder in folders_by_id.items():
                    if folder.parent_folder_id and folder.parent_folder_id in folders_by_id:
                        parent = folders_by_id[folder.parent_folder_id]
                        parent.children.append(folder)
                    else:
                        root_folders.append(folder)

                # Send response
                response = FolderTreeResponse(folders=root_folders)
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"Error getting folder tree: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def get_folder_path(self, sid: str, request) -> None:
        """Get breadcrumb path for a folder"""
        try:
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Get folder and all ancestors using materialized path
                rows = await repo.get_folder_path(conn, request.folder_id)

                path = [
                    {"id": str(row['id']), "name": row['name'], "depth": row['depth']}
                    for row in rows
                ]

                # Send response
                response = FolderPathResponse(path=path)
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"Error getting folder path: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def move_workflow_to_folder(self, sid: str, request) -> None:
        """Move workflow to folder (or root if folder_id is None)"""
        try:
            user_id = await self._get_user_id(sid, request)

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Check access via owner, direct share, or org share
                access = await check_resource_access(conn, user_id, "workflow", request.workflow_id)

                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Workflow not found or access denied"
                    ))
                    return

                if access.permission == Permission.VIEW:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="You need edit permission to move this workflow"
                    ))
                    return

                # Validate folder access if folder_id is provided
                if request.folder_id:
                    if not await repo.can_access_folder(conn, user_id, request.folder_id):
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request.request_id,
                            data={},
                            error="Invalid folder or access denied"
                        ))
                        return

                if access.permission == Permission.OWNER or access.via == "org_share":
                    # Owner or org share: update the workflow's folder_id directly
                    # (org folder structure is shared across all org members)
                    await repo.set_workflow_folder(
                        conn, request.workflow_id, request.folder_id
                    )
                else:
                    # Direct user share recipient: update their personal target_folder_id
                    await repo.set_share_target_folder(
                        conn, request.workflow_id, user_id, request.folder_id
                    )

                # Send success response
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={
                        "success": True,
                        "workflow_id": request.workflow_id,
                        "folder_id": request.folder_id,
                        "message": "Workflow moved successfully"
                    }
                ))

        except Exception as e:
            logger.error(f"Error moving workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))
