"""
Saved Output handler for managing reusable mock/test data.
Allows users to save output data from workflow node executions and reuse it later
for testing and development purposes.
"""

import logging
from typing import Any, Callable, Dict, Optional
from utils.database_pool import DatabasePoolMixin
from wss.handlers.workflow_handler import get_user_org_context
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.sender.responses import (
    SavedOutputInfo,
    SavedOutputListResponse,
    SavedOutputGetResponse,
    SavedOutputCreateResponse,
    SavedOutputUpdateResponse,
    SavedOutputDeleteResponse,
)
from wss.receiver.client_events import (
    SavedOutputCreateRequest,
    SavedOutputListRequest,
    SavedOutputGetRequest,
    SavedOutputUpdateRequest,
    SavedOutputDeleteRequest,
)
from repositories.saved_output import SavedOutputRepo, SavedOutputRow

logger = logging.getLogger(__name__)


def _row_to_info(row: SavedOutputRow) -> SavedOutputInfo:
    """Convert a repo row into the wire ``SavedOutputInfo`` model."""
    return SavedOutputInfo(
        id=str(row.id),
        user_id=str(row.owner_id),
        node_type=row.node_type,
        name=row.name,
        output=row.output or {},
        visibility='public' if row.is_public else 'user',
        created_at=row.created_at.isoformat() if row.created_at else '',
        updated_at=row.updated_at.isoformat() if row.updated_at else '',
    )


class SavedOutputHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for saved output operations with direct socket.io communication"""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        """Register saved output operation events"""
        return {
            "saved_output:create": self.create_saved_output,
            "saved_output:list": self.list_saved_outputs,
            "saved_output:get": self.get_saved_output,
            "saved_output:update": self.update_saved_output,
            "saved_output:delete": self.delete_saved_output,
        }

    async def setup_user(self, sid: str) -> None:
        """Initialize database connection pool on user setup - non-blocking"""
        _ = sid  # Suppress unused parameter warning

    async def create_saved_output(self, sid: str, request: SavedOutputCreateRequest) -> None:
        """Create a new saved output"""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            # Convert visibility to is_public boolean
            is_public = request.visibility == 'public' if hasattr(request, 'visibility') else False

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = SavedOutputRepo(pool)
            async with pool.acquire() as conn:
                # Check saved output limit per node type
                from billing.plan_limits import check_saved_output_limit
                user_data = session.get('user_data', {})
                user_tier = user_data.get('subscription_tier', 'free')
                can_create, limit_error = await check_saved_output_limit(
                    conn, user_id, user_tier, request.node_type
                )
                if not can_create:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error=limit_error
                    ))
                    return

                org_id = await get_user_org_context(conn, user_id)

                row = await repo.create(
                    conn,
                    owner_id=user_id,
                    organization_id=org_id,
                    node_type=request.node_type,
                    name=request.name,
                    output=request.output,
                    is_public=is_public,
                )

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Failed to create saved output"
                    ))
                    return

                response = SavedOutputCreateResponse(
                    success=True,
                    saved_output=_row_to_info(row),
                    message="Saved output created successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"Error creating saved output: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def list_saved_outputs(self, sid: str, request: SavedOutputListRequest) -> None:
        """List saved outputs for a specific node type.
        Returns outputs visible to the user based on visibility rules:
        - Own outputs (any visibility)
        - Public outputs (is_public = true)
        - Outputs shared with the user directly
        - Outputs shared with orgs the user is a member of
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

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

            repo = SavedOutputRepo(pool)
            async with pool.acquire() as conn:
                org_id = await get_user_org_context(conn, user_id)
                rows_with_order = await repo.list_visible(
                    conn,
                    node_type=request.node_type,
                    user_id=user_id,
                    org_id=org_id,
                )

            # Sort by sort_order (own-first) then updated_at desc.
            rows_with_order = sorted(
                rows_with_order,
                key=lambda r: (r[1], -r[0].updated_at.timestamp()),
            )

            saved_outputs = [_row_to_info(row) for row, _ in rows_with_order]

            response = SavedOutputListResponse(saved_outputs=saved_outputs)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"Error listing saved outputs: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def get_saved_output(self, sid: str, request: SavedOutputGetRequest) -> None:
        """Get a specific saved output by ID"""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

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

            repo = SavedOutputRepo(pool)
            async with pool.acquire() as conn:
                org_id = await get_user_org_context(conn, user_id)
                row = await repo.get_visible(
                    conn,
                    saved_output_id=request.saved_output_id,
                    user_id=user_id,
                    org_id=org_id,
                )

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Saved output not found or access denied"
                    ))
                    return

                response = SavedOutputGetResponse(saved_output=_row_to_info(row))
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"Error getting saved output: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def update_saved_output(self, sid: str, request: SavedOutputUpdateRequest) -> None:
        """Update a saved output's name or is_public flag (requires edit permission)"""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

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

            # Build the allowlisted update dict from the request. Empty dict =
            # nothing to change; preserve the historical "No fields to update"
            # error rather than firing a no-op UPDATE.
            updates: Dict[str, Any] = {}
            if request.name is not None:
                updates["name"] = request.name
            if request.visibility is not None:
                updates["is_public"] = (request.visibility == 'public')

            if not updates:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="No fields to update"
                ))
                return

            repo = SavedOutputRepo(pool)
            async with pool.acquire() as conn:
                org_id = await get_user_org_context(conn, user_id)
                has_edit = await repo.user_has_edit(
                    conn,
                    saved_output_id=request.saved_output_id,
                    user_id=user_id,
                    org_id=org_id,
                )

                if not has_edit:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Saved output not found or you don't have edit permission"
                    ))
                    return

                row = await repo.update(
                    conn,
                    saved_output_id=request.saved_output_id,
                    updates=updates,
                )

                if not row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Failed to update saved output"
                    ))
                    return

                response = SavedOutputUpdateResponse(
                    success=True,
                    saved_output=_row_to_info(row),
                    message="Saved output updated successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"Error updating saved output: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def delete_saved_output(self, sid: str, request: SavedOutputDeleteRequest) -> None:
        """Delete a saved output (requires edit permission)"""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

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

            repo = SavedOutputRepo(pool)
            async with pool.acquire() as conn:
                org_id = await get_user_org_context(conn, user_id)
                has_edit = await repo.user_has_edit(
                    conn,
                    saved_output_id=request.saved_output_id,
                    user_id=user_id,
                    org_id=org_id,
                )

                if not has_edit:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Saved output not found or you don't have edit permission"
                    ))
                    return

                await repo.delete(conn, saved_output_id=request.saved_output_id)

                response = SavedOutputDeleteResponse(
                    success=True,
                    message="Saved output deleted successfully",
                    saved_output_id=request.saved_output_id
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))

        except Exception as e:
            logger.error(f"Error deleting saved output: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))
