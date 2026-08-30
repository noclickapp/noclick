"""
Resource handler for managing workflow resources (datasets, blobs).
Handles CRUD for resources, presigned URL generation, and dataset row operations.

SQL for ``workflow_resources`` and ``dataset_rows`` lives in
``repositories/resources.py`` (``ResourceRepo``). Access control still uses
``utils.access_control.check_resource_access`` — that's a cross-domain
concern (workflows + resource_shares + org membership) that doesn't belong
to a resource repo.
"""

import logging

# Maximum upload size: 100 MB (mirrored client-side in useResourceUpload.ts)
MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024
from typing import Dict, Callable, Optional
from utils.database_pool import DatabasePoolMixin
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.sender.responses import (
    ResourceInfo,
    ResourceCreateResponse,
    ResourceListResponse,
    ResourceGetResponse,
    ResourceDeleteResponse,
    ResourceUploadUrlResponse,
    ResourceDownloadUrlResponse,
    DatasetRowInfo,
    ResourceDatasetRowsResponse,
    ResourceDatasetAppendResponse,
    ResourceDatasetUpdateRowResponse,
    ResourceDatasetDeleteRowsResponse,
)
from wss.receiver.client_events import (
    ResourceCreateRequest,
    ResourceListRequest,
    ResourceGetRequest,
    ResourceDeleteRequest,
    ResourceUploadUrlRequest,
    ResourceDownloadUrlRequest,
    ResourceDatasetRowsRequest,
    ResourceDatasetAppendRequest,
    ResourceDatasetUpdateRowRequest,
    ResourceDatasetDeleteRowsRequest,
)
from utils.access_control import check_resource_access, Permission
from repositories.resources import ResourceRepo

logger = logging.getLogger(__name__)

RESOURCE_BUCKET = "workflow-resources"


def _row_to_resource_info(row) -> ResourceInfo:
    """Convert a database row (plain dict from ResourceRepo) to ResourceInfo."""
    return ResourceInfo(
        id=str(row["id"]),
        owner_id=str(row["owner_id"]),
        organization_id=str(row["organization_id"]) if row.get("organization_id") else None,
        workflow_id=str(row["workflow_id"]),
        node_id=row.get("node_id"),
        resource_type=row["resource_type"],
        name=row["name"],
        mime_type=row.get("mime_type"),
        size_bytes=row.get("size_bytes") or 0,
        storage_ref=row.get("storage_ref"),
        metadata=row.get("metadata") or {},
        created_at=row["created_at"].isoformat() if row.get("created_at") else "",
        updated_at=row["updated_at"].isoformat() if row.get("updated_at") else "",
    )


class ResourceHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for workflow resource operations"""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        """Register resource operation events"""
        return {
            "resource:create": self.create_resource,
            "resource:list": self.list_resources,
            "resource:get": self.get_resource,
            "resource:delete": self.delete_resource,
            "resource:upload_url": self.get_upload_url,
            "resource:download_url": self.get_download_url,
            "resource:dataset:rows": self.get_dataset_rows,
            "resource:dataset:append": self.append_dataset_rows,
            "resource:dataset:update_row": self.update_dataset_row,
            "resource:dataset:delete_rows": self.delete_dataset_rows,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def _get_auth(self, sid: str, request):
        """Get authenticated user_id and pool, or send error and return None."""
        session = await self.sio.get_session(sid)
        user_id = session.get("user_id")
        if not user_id:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error="User not authenticated"
            ))
            return None, None

        pool = await self.get_pool()
        if not pool:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error="Database connection not available"
            ))
            return None, None

        return user_id, pool

    async def _check_workflow_access(
        self, user_id: str, workflow_id: str, request, sid,
        min_permission: Permission = Permission.VIEW,
    ) -> bool:
        """Check workflow access via a short-lived acquire.

        Sends an error response and returns False when access is denied or
        insufficient for ``min_permission``. Returns True on success.
        """
        pool = await self.get_pool()
        async with pool.acquire() as conn:
            access = await check_resource_access(conn, user_id, "workflow", workflow_id)

        if not access.has_access:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error="Workflow not found or access denied"
            ))
            return False

        if min_permission == Permission.EDIT and access.permission not in (Permission.EDIT, Permission.OWNER):
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error="Edit access required"
            ))
            return False

        return True

    async def _get_resource_with_access(
        self, user_id: str, resource_id: str, request, sid,
        min_permission: Permission = Permission.VIEW,
    ) -> Optional[dict]:
        """Fetch a resource row through the repo and check workflow access.

        Returns the resource dict, or None (with an error already sent)
        when the resource is missing or the caller can't access it.
        """
        pool = await self.get_pool()
        repo = ResourceRepo(pool)
        resource = await repo.get_resource(resource_id)
        if resource is None:
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error="Resource not found"
            ))
            return None

        if not await self._check_workflow_access(
            user_id, str(resource["workflow_id"]), request, sid, min_permission,
        ):
            return None

        return resource

    # ── CRUD ────────────────────────────────────────────────────────────

    async def create_resource(self, sid: str, request: ResourceCreateRequest) -> None:
        """Create a new workflow resource"""
        try:
            user_id, pool = await self._get_auth(sid, request)
            if not user_id:
                return

            # Enforce upload size limit
            if request.size_bytes and request.size_bytes > MAX_UPLOAD_SIZE_BYTES:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={},
                    error=f"File too large. Maximum size is {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB"
                ))
                return

            if not await self._check_workflow_access(
                user_id, request.workflow_id, request, sid, Permission.EDIT,
            ):
                return

            repo = ResourceRepo(pool)
            org_id = await repo.get_workflow_organization_id(request.workflow_id)
            row = await repo.create_resource(
                owner_id=user_id,
                organization_id=org_id,
                workflow_id=request.workflow_id,
                node_id=request.node_id,
                resource_type=request.resource_type,
                name=request.name,
                mime_type=request.mime_type,
                size_bytes=request.size_bytes or 0,
                storage_ref=request.storage_ref,
                metadata=request.metadata or {},
            )

            response = ResourceCreateResponse(
                success=True,
                resource=_row_to_resource_info(row),
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error creating resource: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    async def list_resources(self, sid: str, request: ResourceListRequest) -> None:
        """List resources the user can access, with optional workflow/type filters"""
        try:
            user_id, pool = await self._get_auth(sid, request)
            if not user_id:
                return

            repo = ResourceRepo(pool)
            rows = await repo.list_accessible_resources(
                user_id=user_id,
                workflow_id=request.workflow_id,
                resource_type=request.resource_type,
                limit=request.limit,
                offset=request.offset,
            )

            # Skip (and log) any malformed row instead of failing the whole list —
            # one bad row (e.g. a legacy double-encoded metadata value that won't
            # validate as ResourceInfo) must not hide every resource for the workflow.
            resources = []
            for r in rows:
                try:
                    resources.append(_row_to_resource_info(r))
                except Exception as e:
                    logger.warning(f"[Resource] Skipping malformed resource row {r.get('id')}: {e}")

            response = ResourceListResponse(resources=resources)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error listing resources: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    async def get_resource(self, sid: str, request: ResourceGetRequest) -> None:
        """Get a single resource by ID"""
        try:
            user_id, pool = await self._get_auth(sid, request)
            if not user_id:
                return

            row = await self._get_resource_with_access(
                user_id, request.resource_id, request, sid,
            )
            if not row:
                return

            response = ResourceGetResponse(resource=_row_to_resource_info(row))
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error getting resource: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    async def delete_resource(self, sid: str, request: ResourceDeleteRequest) -> None:
        """Delete a resource (and its R2 blob if applicable)"""
        try:
            user_id, pool = await self._get_auth(sid, request)
            if not user_id:
                return

            row = await self._get_resource_with_access(
                user_id, request.resource_id, request, sid, Permission.EDIT,
            )
            if not row:
                return

            # Delete R2 blob if storage_ref exists
            storage_ref = row.get("storage_ref")
            if storage_ref:
                try:
                    from utils.r2_cloudflare import delete_files_from_r2_async_native
                    await delete_files_from_r2_async_native(RESOURCE_BUCKET, [storage_ref])
                except Exception as e:
                    logger.warning(f"Failed to delete R2 blob {storage_ref}: {e}")

            # Delete from DB (CASCADE handles dataset_rows)
            repo = ResourceRepo(pool)
            await repo.delete_resource(request.resource_id)

            response = ResourceDeleteResponse(success=True, message="Resource deleted")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error deleting resource: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    # ── Presigned URLs ──────────────────────────────────────────────────

    async def get_upload_url(self, sid: str, request: ResourceUploadUrlRequest) -> None:
        """Generate a presigned PUT URL for uploading a blob"""
        try:
            user_id, pool = await self._get_auth(sid, request)
            if not user_id:
                return

            row = await self._get_resource_with_access(
                user_id, request.resource_id, request, sid, Permission.EDIT,
            )
            if not row:
                return

            # Build R2 key
            storage_key = f"{row['owner_id']}/{row['workflow_id']}/{row['id']}/{request.filename}"

            from utils.r2_cloudflare import generate_presigned_upload_url
            upload_url = generate_presigned_upload_url(
                RESOURCE_BUCKET,
                storage_key,
                request.content_type,
                content_length=int(row.get("size_bytes") or 0),
            )

            # Update resource with storage_ref and mime_type
            repo = ResourceRepo(pool)
            await repo.update_storage_ref(
                request.resource_id, storage_key, request.content_type,
            )

            response = ResourceUploadUrlResponse(
                upload_url=upload_url, storage_ref=storage_key
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error generating upload URL: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    async def get_download_url(self, sid: str, request: ResourceDownloadUrlRequest) -> None:
        """Generate a presigned GET URL for downloading a blob"""
        try:
            user_id, pool = await self._get_auth(sid, request)
            if not user_id:
                return

            row = await self._get_resource_with_access(
                user_id, request.resource_id, request, sid,
            )
            if not row:
                return

            storage_ref = row.get("storage_ref")
            if not storage_ref:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={},
                    error="Resource has no stored file"
                ))
                return

            from utils.r2_cloudflare import get_public_download_url
            download_url = get_public_download_url(storage_ref)

            response = ResourceDownloadUrlResponse(download_url=download_url)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error generating download URL: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    # ── Dataset Row Operations ──────────────────────────────────────────

    async def get_dataset_rows(self, sid: str, request: ResourceDatasetRowsRequest) -> None:
        """Get paginated rows from a dataset resource"""
        try:
            user_id, pool = await self._get_auth(sid, request)
            if not user_id:
                return

            row = await self._get_resource_with_access(
                user_id, request.resource_id, request, sid,
            )
            if not row:
                return

            if row["resource_type"] != "dataset":
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={},
                    error="Resource is not a dataset"
                ))
                return

            repo = ResourceRepo(pool)
            page_rows, total_count = await repo.list_dataset_rows_with_count(
                request.resource_id, request.limit, request.offset,
            )

            dataset_rows = [
                DatasetRowInfo(
                    id=str(r["id"]),
                    row_index=r["row_index"],
                    data=r["data"],
                    created_at=r["created_at"].isoformat() if r.get("created_at") else "",
                )
                for r in page_rows
            ]

            response = ResourceDatasetRowsResponse(
                rows=dataset_rows, total_count=total_count
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error getting dataset rows: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    async def append_dataset_rows(self, sid: str, request: ResourceDatasetAppendRequest) -> None:
        """Append rows to a dataset resource"""
        try:
            user_id, pool = await self._get_auth(sid, request)
            if not user_id:
                return

            row = await self._get_resource_with_access(
                user_id, request.resource_id, request, sid, Permission.EDIT,
            )
            if not row:
                return

            if row["resource_type"] != "dataset":
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={},
                    error="Resource is not a dataset"
                ))
                return

            repo = ResourceRepo(pool)
            inserted = await repo.append_dataset_rows(
                request.resource_id,
                request.rows,
                row.get("metadata") or {},
            )

            response = ResourceDatasetAppendResponse(
                success=True, inserted_count=inserted
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error appending dataset rows: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    async def update_dataset_row(self, sid: str, request: ResourceDatasetUpdateRowRequest) -> None:
        """Update a single row in a dataset"""
        try:
            user_id, pool = await self._get_auth(sid, request)
            if not user_id:
                return

            row = await self._get_resource_with_access(
                user_id, request.resource_id, request, sid, Permission.EDIT,
            )
            if not row:
                return

            repo = ResourceRepo(pool)
            updated = await repo.update_dataset_row_and_touch(
                request.row_id, request.resource_id, request.data,
            )

            if not updated:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="Row not found"
                ))
                return

            response = ResourceDatasetUpdateRowResponse(success=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error updating dataset row: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))

    async def delete_dataset_rows(self, sid: str, request: ResourceDatasetDeleteRowsRequest) -> None:
        """Delete rows from a dataset"""
        try:
            user_id, pool = await self._get_auth(sid, request)
            if not user_id:
                return

            row = await self._get_resource_with_access(
                user_id, request.resource_id, request, sid, Permission.EDIT,
            )
            if not row:
                return

            repo = ResourceRepo(pool)
            deleted_count = await repo.delete_dataset_rows(
                request.resource_id,
                request.row_ids,
                row.get("metadata") or {},
            )

            response = ResourceDatasetDeleteRowsResponse(
                success=True, deleted_count=deleted_count
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error deleting dataset rows: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error=str(e)
            ))
