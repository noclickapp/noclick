"""
Share handler for managing resource sharing and forking.
Allows users to share workflows and databases with other users (by email) or organizations.
Also handles forking resources to create independent copies.
"""

import logging
import secrets
import uuid
from typing import Dict, Callable, Optional
from utils.database_pool import DatabasePoolMixin
from utils.access_control import check_resource_access
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent, ShareNotificationEvent
from wss.sender.responses import (
    ShareInfo,
    ShareCreateResponse,
    ShareListResponse,
    ShareUpdateResponse,
    ShareDeleteResponse,
    ShareLeaveResponse,
    ShareInviteLinkResponse,
    ShareInviteAcceptResponse,
    SharedResourceInfo,
    ShareListSharedWithMeResponse,
    ForkedResourceInfo,
    ResourceForkResponse,
)
from repositories.share import ShareRepo, ShareRow
from wss.receiver.client_events import (
    ShareCreateRequest,
    ShareListRequest,
    ShareUpdateRequest,
    ShareDeleteRequest,
    ShareLeaveRequest,
    ShareListSharedWithMeRequest,
    ShareInviteLinkRequest,
    ShareInviteAcceptRequest,
    ResourceForkRequest,
)
from utils.slack import send_activity_notification_background, extract_user_name
from utils.analytics import log_activity_background, set_person_properties_background
from utils.analytics_events import Events
from utils.hosted_defaults import frontend_url

logger = logging.getLogger(__name__)


def _invalidate_database_cache(org_id: Optional[str] = None) -> None:
    """
    Invalidate the user database handler's cache when shares change.
    This ensures users see updated share state immediately.
    """
    try:
        from wss.receiver.receiver import get_receiver_instance
        from wss.receiver.event_routing import Handler

        receiver = get_receiver_instance()
        if receiver and receiver.handler_instances:
            db_handler = receiver.handler_instances.get(Handler.USER_DATABASE)
            if db_handler and hasattr(db_handler, 'clear_tables_cache'):
                db_handler.clear_tables_cache(org_id)
    except Exception as e:
        logger.warning(f"Failed to invalidate database cache: {e}")


class ShareHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for resource sharing operations with direct socket.io communication"""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        """Register share operation events"""
        return {
            "share:create": self.create_share,
            "share:list": self.list_shares,
            "share:update": self.update_share,
            "share:delete": self.delete_share,
            "share:leave": self.leave_share,
            "share:list_shared_with_me": self.list_shared_with_me,
            "share:invite_link": self.create_invite_link,
            "share:invite_accept": self.accept_invite,
            "resource:fork": self.fork_resource,
        }

    async def setup_user(self, sid: str) -> None:
        """Initialize database connection pool and kick off background
        conversion of pending share invites for this user's email."""
        from utils.async_helpers import spawn
        spawn(
            self._convert_pending_invites(sid),
            name=f"share-convert-pending-invites:{sid}",
        )

    async def _convert_pending_invites(self, sid: str) -> None:
        """Convert pending share invites (target_email-only) into real
        shares (target_user_id set) for the user that just connected."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")
            user_email = session.get("user_data", {}).get("email")

            if not user_id or not user_email:
                return

            pool = await self.get_pool()
            if not pool:
                return
            repo = ShareRepo(pool)

            pending_invites = await repo.list_pending_invites_for_email(user_email)
            if not pending_invites:
                return

            logger.info(
                f"Found {len(pending_invites)} pending share invites for {user_email}"
            )

            for invite in pending_invites:
                await repo.link_pending_invite_to_user(invite.id, user_id)
                logger.info(
                    f"Converted pending invite {invite.id} for {invite.resource_type} "
                    f"{invite.resource_id} to user {user_id}"
                )

        except Exception as e:
            logger.error(f"Error processing pending invites for sid {sid}: {e}")

    async def _build_share_info(self, share: ShareRow, repo: ShareRepo) -> ShareInfo:
        """Build ShareInfo from a ShareRow with additional repo lookups.

        Presentation-only shaping (display names, public URL) stays here;
        the underlying SQL lives in ShareRepo.
        """
        target_display_name = None
        target_org_name = None
        target_org_icon_url = None
        target_avatar_url = None
        shared_by_email = None
        public_url = None

        shared_by_email = await repo.get_user_email(share.shared_by)

        if share.target_type == "public":
            target_display_name = "Anyone with the link"
            public_url = f"{frontend_url()}/share/{share.resource_id}"
        elif share.target_type == "organization" and share.target_org_id:
            org = await repo.get_org_display(share.target_org_id)
            if org:
                target_org_name = org.name
                target_display_name = org.name
                target_org_icon_url = org.icon_url
        elif share.target_type == "user":
            if share.target_user_id:
                user = await repo.get_user_display(share.target_user_id)
                if user:
                    target_display_name = user.display_name or user.email
                    target_avatar_url = user.avatar_url
            elif share.target_email:
                target_display_name = share.target_email

        return ShareInfo(
            id=share.id,
            resource_type=share.resource_type,
            resource_id=share.resource_id,
            target_type=share.target_type,
            target_user_id=share.target_user_id,
            target_email=share.target_email,
            target_avatar_url=target_avatar_url,
            target_org_id=share.target_org_id,
            target_org_name=target_org_name,
            target_org_icon_url=target_org_icon_url,
            target_display_name=target_display_name,
            permission=share.permission,
            shared_by=share.shared_by,
            shared_by_email=shared_by_email,
            created_at=share.created_at.isoformat() if share.created_at else "",
            is_pending=share.target_email is not None and share.target_user_id is None,
            public_url=public_url,
        )

    async def create_share(self, sid: str, request: ShareCreateRequest) -> None:
        """Create a new share for a resource."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id, data={}, error="User not authenticated"
                    ),
                )
                return

            # Validate request based on target type
            if request.target_type == "user" and not request.target_email:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Email is required when sharing with a user",
                    ),
                )
                return

            if request.target_type == "organization" and not request.target_org_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Organization ID is required when sharing with an organization",
                    ),
                )
                return

            # Public shares are only allowed for workflows
            if request.target_type == "public" and request.resource_type != "workflow":
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Public sharing is only available for workflows",
                    ),
                )
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Database connection not available",
                    ),
                )
                return
            repo = ShareRepo(pool)

            if not await repo.can_manage_shares(
                user_id, request.resource_type, request.resource_id
            ):
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="You don't have permission to share this resource",
                    ),
                )
                return

            # Org folders cannot be shared with non-org users
            if request.target_type == "user" and request.resource_type == "workflow_folder":
                resource_org_id = await repo.get_resource_org_id(
                    request.resource_type, request.resource_id
                )
                if resource_org_id:
                    if request.target_email:
                        target_user_id = await repo.find_user_id_by_email(request.target_email)
                        if target_user_id:
                            target_in_org = await repo.is_org_member(resource_org_id, target_user_id)
                            if not target_in_org:
                                await send_event(
                                    self.sio,
                                    sid,
                                    ResponseEvent(
                                        request_id=request.request_id,
                                        data={},
                                        error="Organization folders can only be shared with members of the same organization",
                                    ),
                                )
                                return
                        else:
                            await send_event(
                                self.sio,
                                sid,
                                ResponseEvent(
                                    request_id=request.request_id,
                                    data={},
                                    error="Organization folders can only be shared with existing members of the organization",
                                ),
                            )
                            return

            # Validate member share target restrictions
            # (Members can only share within their org, admins/owners have no restrictions)
            is_valid, error_msg = await repo.validate_member_share_target(
                user_id,
                request.resource_type,
                request.resource_id,
                request.target_type,
                request.target_email,
                request.target_org_id,
            )
            if not is_valid:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error=error_msg,
                    ),
                )
                return

            # Get resource name for notifications
            resource_name = await repo.get_resource_name(
                request.resource_type, request.resource_id
            )

            share_row: Optional[ShareRow]
            if request.target_type == "user":
                target_user_id = await repo.find_user_id_by_email(request.target_email)

                if target_user_id:
                    existing_id = await repo.find_user_share_id(
                        request.resource_type, request.resource_id, target_user_id
                    )
                    if existing_id:
                        share_row = await repo.update_share_permission(
                            existing_id, request.permission, touch_updated_at=True
                        )
                    else:
                        share_row = await repo.insert_user_share(
                            request.resource_type,
                            request.resource_id,
                            target_user_id,
                            request.permission,
                            user_id,
                        )

                    # Send notification to target user (1:1 share) unless self-share
                    if share_row is not None and target_user_id != user_id:
                        sharer = await repo.get_user_email_and_name(user_id)
                        if sharer and resource_name:
                            notification = ShareNotificationEvent(
                                resource_type=request.resource_type,
                                resource_id=request.resource_id,
                                resource_name=resource_name,
                                permission=request.permission,
                                shared_by_email=sharer.email,
                                shared_by_name=sharer.name,
                                share_id=share_row.id,
                            )
                            await send_event(
                                self.sio,
                                sid,
                                notification,
                                user_id=target_user_id,
                            )
                else:
                    # User doesn't exist — pending invite path
                    existing_id = await repo.find_pending_share_id(
                        request.resource_type, request.resource_id, request.target_email
                    )
                    if existing_id:
                        share_row = await repo.update_share_permission(
                            existing_id, request.permission, touch_updated_at=True
                        )
                    else:
                        share_row = await repo.insert_pending_share(
                            request.resource_type,
                            request.resource_id,
                            request.target_email,
                            request.permission,
                            user_id,
                        )
                    # TODO: Send invite email to the non-user
                    # This would integrate with an email service
            elif request.target_type == "organization":
                existing_id = await repo.find_org_share_id(
                    request.resource_type, request.resource_id, request.target_org_id
                )
                if existing_id:
                    share_row = await repo.update_share_permission(
                        existing_id, request.permission, touch_updated_at=True
                    )
                else:
                    share_row = await repo.insert_org_share(
                        request.resource_type,
                        request.resource_id,
                        request.target_org_id,
                        request.permission,
                        user_id,
                    )
                # No notification for org-wide shares (would be spam)
            else:
                # Public share — only workflows (validated earlier)
                share_row = await repo.upsert_public_share(
                    request.resource_type, request.resource_id, user_id
                )

            if share_row is None:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Failed to create share",
                    ),
                )
                return

            share = await self._build_share_info(share_row, repo)

            # Invalidate database cache so recipients see the share immediately
            if request.resource_type == "database":
                target_org = request.target_org_id if request.target_type == "organization" else None
                _invalidate_database_cache(target_org)

            # Send Slack activity notification for workflow shares
            if request.resource_type == "workflow":
                user_data = session.get("user_data", {})
                user_name = extract_user_name(user_data)
                user_email = user_data.get("email", "unknown@example.com")
                slack_thread_ts = session.get("slack_thread_ts")
                target_desc = (
                    request.target_email
                    if request.target_type == "user"
                    else "organization" if request.target_type == "organization"
                    else "public"
                )
                send_activity_notification_background(
                    user_name, user_email, "🔗 Shared Workflow",
                    details={
                        "Resource": resource_name or request.resource_id[:8] + "...",
                        "Shared with": target_desc,
                        "Permission": request.permission,
                    },
                    thread_ts=slack_thread_ts
                )

            response = ShareCreateResponse(
                success=True, share=share, message="Resource shared successfully"
            )
            await send_event(
                self.sio,
                sid,
                ResponseEvent(
                    request_id=request.request_id, data=response.model_dump()
                ),
            )

        except Exception as e:
            logger.error(f"Error creating share: {e}", exc_info=True)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request.request_id, data={}, error=str(e)),
            )

    async def create_invite_link(self, sid: str, request: ShareInviteLinkRequest) -> None:
        """Mint (or return the existing) shareable collaboration invite link for a
        workflow. Personal-workflow-only (org workflows use the ShareDialog).
        Idempotent: re-minting returns the same active token.

        Access model (the viral loop needs collaborators to re-share the link):
        ANY user with access to the workflow may FETCH the existing active link.
        Only the OWNER may CREATE it — a non-owner minting a link that grants edit
        access to someone else's workflow would be a privilege escalation."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id, data={}, error="User not authenticated"
                    ),
                )
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id, data={}, error="Database connection not available"
                    ),
                )
                return

            repo = ShareRepo(pool)
            workflow = await repo.get_workflow_for_invite(request.workflow_id)
            if not workflow:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id, data={}, error="Workflow not found"
                    ),
                )
                return

            is_owner = workflow.owner_id == user_id
            if not is_owner:
                # check_resource_access takes a raw conn — grab one for it.
                async with pool.acquire() as conn:
                    access = await check_resource_access(
                        conn, user_id, "workflow", request.workflow_id
                    )
                if not access.has_access:
                    await send_event(
                        self.sio,
                        sid,
                        ResponseEvent(
                            request_id=request.request_id,
                            data={},
                            error="You don't have access to this workflow",
                        ),
                    )
                    return

            # Real (non-personal) org workflows are scoped to the org (members
            # manage access via the ShareDialog); invite links are personal-only in
            # v1. Every user's PERSONAL WORKSPACE is itself backed by a real org row
            # (is_personal_workspace=true, see migration 20260305000001), so a
            # non-null organization_id no longer implies "org workflow" — gate on
            # is_personal_workspace, otherwise personal-workspace flows are wrongly
            # rejected and the share link never mints.
            if workflow.organization_id and not workflow.is_personal_workspace:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Invite links aren't available for organization workflows",
                    ),
                )
                return

            existing = await repo.get_active_invite_link(request.workflow_id)

            # Only the owner creates the link; collaborators fetch-only.
            if not existing and is_owner:
                token = secrets.token_urlsafe(16)
                existing = await repo.create_invite_link(request.workflow_id, token, user_id)
                if existing is None:
                    # Concurrent mint won the partial unique index — re-read it.
                    existing = await repo.get_active_invite_link(request.workflow_id)

            if not existing:
                # Non-owner and no active link exists (owner hasn't enabled it
                # or turned it off), or the owner's create failed.
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error=(
                            "Failed to create invite link"
                            if is_owner
                            else "This workflow doesn't have an active invite link"
                        ),
                    ),
                )
                return

            response = ShareInviteLinkResponse(
                success=True,
                token=existing.token,
                url=f"{frontend_url()}/i/{existing.token}",
                permission=existing.permission,
            )
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request.request_id, data=response.model_dump()),
            )

        except Exception as e:
            logger.error(f"Error creating invite link: {e}", exc_info=True)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request.request_id, data={}, error=str(e)),
            )

    async def accept_invite(self, sid: str, request: ShareInviteAcceptRequest) -> None:
        """Redeem a workflow invite link: grant the current user 'edit' collaborator
        access to the linked workflow by writing an ordinary resource_shares
        direct-share row (so access control / collab tokens / presence all work
        unchanged). Idempotent — re-accepting just re-upserts the share."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id, data={}, error="User not authenticated"
                    ),
                )
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id, data={}, error="Database connection not available"
                    ),
                )
                return

            repo = ShareRepo(pool)
            link = await repo.get_invite_link_details(request.token)

            if not link:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="This invite link is no longer valid",
                    ),
                )
                return

            workflow_id = link.workflow_id
            owner_id = link.owner_id
            permission = link.permission
            workflow_name = link.workflow_name

            # Defense in depth: invite links are owner-minted (create_invite_link is
            # owner-only). Reject any link whose creator is not the workflow owner —
            # e.g. one inserted directly through a mis-scoped RLS path — so a forged
            # link can't grant access to a workflow its creator never owned.
            if link.created_by != owner_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="This invite link is no longer valid",
                    ),
                )
                return

            # Owner opening their own link — already has full access, nothing to grant.
            joined = owner_id != user_id
            redemption_result = None
            if joined:
                # Real transaction now — the 2026-07-01 native pool supports it.
                # Kept idempotent regardless (ON CONFLICT clauses) so a client
                # retry after a network error still converges.
                redemption_result = await repo.redeem_invite(
                    workflow_id=workflow_id,
                    user_id=user_id,
                    permission=permission,
                    owner_id=owner_id,
                    invite_token=request.token,
                )

                # First-touch acquisition tag — keyed on the FIRST redemption (not the
                # onboarding row), so a retry after a partial failure still attributes
                # exactly once. set_once never overwrites; external analytics, so it
                # runs after the DB writes. (invite_redemptions is the durable record.)
                if redemption_result.first_redemption:
                    set_person_properties_background(
                        user_id,
                        {
                            "signup_source": "referral",
                            "referred_by": owner_id,
                            "referred_via_workflow": workflow_id,
                            "invite_token": request.token,
                        },
                        set_once=True,
                    )

            response = ShareInviteAcceptResponse(
                success=True,
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                # Refresh the client JWT only when a new onboarding row was minted
                # (that's what changes the onboarding_completed claim); an
                # already-onboarded joiner needs no refresh.
                refresh_jwt=redemption_result is not None and redemption_result.onboarding_row_created,
            )
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request.request_id, data=response.model_dump()),
            )

        except Exception as e:
            logger.error(f"Error accepting invite: {e}", exc_info=True)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request.request_id, data={}, error=str(e)),
            )

    async def list_shares(self, sid: str, request: ShareListRequest) -> None:
        """List all shares for a resource."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id, data={}, error="User not authenticated"
                    ),
                )
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Database connection not available",
                    ),
                )
                return

            repo = ShareRepo(pool)
            if not await repo.can_manage_shares(
                user_id, request.resource_type, request.resource_id
            ):
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="You don't have permission to view shares for this resource",
                    ),
                )
                return

            rows = await repo.list_shares_for_resource(
                request.resource_type, request.resource_id
            )

            shares = []
            for row in rows:
                share = await self._build_share_info(row, repo)
                shares.append(share)

            response = ShareListResponse(shares=shares)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(
                    request_id=request.request_id, data=response.model_dump()
                ),
            )

        except Exception as e:
            logger.error(f"Error listing shares: {e}", exc_info=True)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request.request_id, data={}, error=str(e)),
            )

    async def update_share(self, sid: str, request: ShareUpdateRequest) -> None:
        """Update a share's permission."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id, data={}, error="User not authenticated"
                    ),
                )
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Database connection not available",
                    ),
                )
                return

            repo = ShareRepo(pool)
            share_row = await repo.get_share_by_id(request.share_id)

            if not share_row:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Share not found",
                    ),
                )
                return

            if not await repo.can_manage_shares(
                user_id,
                share_row.resource_type,
                share_row.resource_id,
            ):
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="You don't have permission to update this share",
                    ),
                )
                return

            # Preserves the original quirk: update_share does NOT touch updated_at.
            updated = await repo.update_share_permission(
                request.share_id, request.permission, touch_updated_at=False
            )

            if not updated:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Failed to update share",
                    ),
                )
                return

            share = await self._build_share_info(updated, repo)

            # Invalidate database cache so permission changes take effect immediately
            if updated.resource_type == "database":
                target_org = updated.target_org_id if updated.target_org_id else None
                _invalidate_database_cache(target_org)

            response = ShareUpdateResponse(
                success=True, share=share, message="Share updated successfully"
            )
            await send_event(
                self.sio,
                sid,
                ResponseEvent(
                    request_id=request.request_id, data=response.model_dump()
                ),
            )

        except Exception as e:
            logger.error(f"Error updating share: {e}", exc_info=True)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request.request_id, data={}, error=str(e)),
            )

    async def delete_share(self, sid: str, request: ShareDeleteRequest) -> None:
        """Delete a share."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id, data={}, error="User not authenticated"
                    ),
                )
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Database connection not available",
                    ),
                )
                return

            repo = ShareRepo(pool)
            share_row = await repo.get_share_by_id(request.share_id)

            if not share_row:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Share not found",
                    ),
                )
                return

            if not await repo.can_manage_shares(
                user_id,
                share_row.resource_type,
                share_row.resource_id,
            ):
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="You don't have permission to delete this share",
                    ),
                )
                return

            deleted = await repo.delete_share(request.share_id)

            if not deleted:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Share not found",
                    ),
                )
                return

            # Invalidate database cache so the unshared database disappears immediately
            if share_row.resource_type == "database":
                target_org = share_row.target_org_id if share_row.target_org_id else None
                _invalidate_database_cache(target_org)

            response = ShareDeleteResponse(
                success=True,
                message="Share deleted successfully",
                share_id=request.share_id,
            )
            await send_event(
                self.sio,
                sid,
                ResponseEvent(
                    request_id=request.request_id, data=response.model_dump()
                ),
            )

        except Exception as e:
            logger.error(f"Error deleting share: {e}", exc_info=True)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request.request_id, data={}, error=str(e)),
            )

    async def leave_share(self, sid: str, request: ShareLeaveRequest) -> None:
        """Remove the caller's OWN direct share for a resource (self-service
        unshare). Used when a collaborator wants a shared item to stop showing on
        their end. No manage-shares check — you can always drop your own access.
        Idempotent: succeeds even if no row exists (e.g. access came via a folder
        or org share rather than a direct user share)."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id, data={}, error="User not authenticated"
                    ),
                )
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Database connection not available",
                    ),
                )
                return

            repo = ShareRepo(pool)
            # removed=False means there was no direct user-share to drop (access
            # came via an org/folder share, which this can't remove) — the
            # client uses this to avoid a vanish/reappear.
            removed = await repo.delete_user_share(
                request.resource_type, request.resource_id, user_id
            )

            response = ShareLeaveResponse(
                success=True, resource_id=request.resource_id, removed=removed
            )
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request.request_id, data=response.model_dump()),
            )

        except Exception as e:
            logger.error(f"Error leaving share: {e}", exc_info=True)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request.request_id, data={}, error=str(e)),
            )

    async def list_shared_with_me(
        self, sid: str, request: ShareListSharedWithMeRequest
    ) -> None:
        """List resources shared with the current user."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id, data={}, error="User not authenticated"
                    ),
                )
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Database connection not available",
                    ),
                )
                return

            repo = ShareRepo(pool)
            rows = await repo.list_shared_with_me(user_id, request.resource_type)

            resources = []
            for row in rows:
                if row.resource_name:  # Resource still exists
                    resources.append(
                        SharedResourceInfo(
                            resource_type=row.resource_type,
                            resource_id=row.resource_id,
                            resource_name=row.resource_name,
                            resource_description=row.resource_description,
                            permission=row.permission,
                            shared_by_email=row.shared_by_email or "Unknown",
                            shared_by_name=row.shared_by_name,
                            shared_at=row.shared_at.isoformat() if row.shared_at else "",
                            organization_id=row.organization_id,
                            organization_name=row.organization_name,
                        )
                    )

            response = ShareListSharedWithMeResponse(resources=resources)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(
                    request_id=request.request_id, data=response.model_dump()
                ),
            )

        except Exception as e:
            logger.error(f"Error listing shared resources: {e}", exc_info=True)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request.request_id, data={}, error=str(e)),
            )

    async def fork_resource(self, sid: str, request: ResourceForkRequest) -> None:
        """
        Fork a resource (workflow or database) to a new location.
        Creates an independent copy that the user owns (personal) or has edit access to (org).
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get("user_id")

            if not user_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id, data={}, error="User not authenticated"
                    ),
                )
                return

            # Validate destination
            if request.destination_type == "organization" and not request.destination_org_id:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Organization ID is required when forking to an organization",
                    ),
                )
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Database connection not available",
                    ),
                )
                return

            repo = ShareRepo(pool)
            if not await repo.can_access_resource(
                user_id, request.resource_type, request.resource_id
            ):
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="You don't have access to the source resource",
                    ),
                )
                return

            # If forking to org, verify user is a member
            if request.destination_type == "organization":
                is_member = await repo.is_org_member(request.destination_org_id, user_id)
                if not is_member:
                    await send_event(
                        self.sio,
                        sid,
                        ResponseEvent(
                            request_id=request.request_id,
                            data={},
                            error="You must be a member of the target organization to fork there",
                        ),
                    )
                    return

            # Fork based on resource type
            if request.resource_type == "workflow":
                # Check workflow limit before forking. check_workflow_limit
                # takes a raw conn, so grab one for this call.
                from billing.plan_limits import check_workflow_limit
                user_data = session.get("user_data", {})
                user_tier = user_data.get("subscription_tier", "free")
                async with pool.acquire() as conn:
                    can_create, limit_error = await check_workflow_limit(conn, user_id, user_tier)
                if not can_create:
                    await send_event(
                        self.sio, sid,
                        ResponseEvent(request_id=request.request_id, data={}, error=limit_error),
                    )
                    return

                forked = await self._fork_workflow(
                    repo, user_id, request.resource_id, request.destination_type,
                    request.destination_org_id, request.new_name
                )
            elif request.resource_type == "database":
                forked = await self._fork_database(
                    repo, user_id, request.resource_id, request.destination_type,
                    request.destination_org_id, request.new_name, request.include_data
                )
            else:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error=f"Unsupported resource type: {request.resource_type}",
                    ),
                )
                return

            if not forked:
                await send_event(
                    self.sio,
                    sid,
                    ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Failed to fork resource",
                    ),
                )
                return

            # Send Slack activity notification for workflow forks
            if request.resource_type == "workflow":
                user_data = session.get("user_data", {})
                user_name = extract_user_name(user_data)
                user_email = user_data.get("email", "unknown@example.com")
                slack_thread_ts = session.get("slack_thread_ts")
                send_activity_notification_background(
                    user_name, user_email, "🍴 Forked Workflow",
                    details={
                        "Original": forked.forked_from_name,
                        "New name": forked.name,
                    },
                    thread_ts=slack_thread_ts
                )
                new_id = getattr(forked, 'id', None)
                log_activity_background(Events.WORKFLOW_FORKED, user_id, {
                    "source_workflow_id": str(request.resource_id),
                    "new_workflow_id": str(new_id) if new_id else None,
                    "destination_type": request.destination_type,
                    "source_name": forked.forked_from_name,
                })

            response = ResourceForkResponse(
                success=True,
                forked_resource=forked,
                message=f"Successfully forked {request.resource_type}",
            )
            await send_event(
                self.sio,
                sid,
                ResponseEvent(
                    request_id=request.request_id, data=response.model_dump()
                ),
            )

        except Exception as e:
            logger.error(f"Error forking resource: {e}", exc_info=True)
            await send_event(
                self.sio,
                sid,
                ResponseEvent(request_id=request.request_id, data={}, error=str(e)),
            )

    async def _fork_workflow(
        self,
        repo: ShareRepo,
        user_id: str,
        source_workflow_id: str,
        destination_type: str,
        destination_org_id: Optional[str],
        new_name: Optional[str],
    ) -> Optional[ForkedResourceInfo]:
        """Fork a workflow to a new location."""
        source = await repo.get_workflow_source(source_workflow_id)
        if not source:
            return None

        # Generate new ID and name
        new_id = str(uuid.uuid4())
        forked_name = new_name or f"Copy of {source.name}"

        # Create new workflow
        # owner_id is always the user who forked (workflows require an owner)
        # org_id is set to destination org, or personal workspace org for personal forks
        owner_id = user_id
        if destination_type == "organization":
            org_id = destination_org_id
        else:
            org_id = await repo.get_user_primary_org(user_id)

        workflow_data = source.workflow
        if isinstance(workflow_data, dict):
            # Strip author-specific runtime state so forked workflows start clean —
            # incl. last-run status/timestamp/error so a fork never shows the source's
            # run history (a forked workflow has never been run by its new owner).
            _strip_keys = (
                "disabled", "mockedOutput", "output", "_outputStoredLocally", "_outputSizeBytes",
                "_lastRunStatus", "_lastRunAt", "_lastRunError",
            )

            def _strip_credential_ids(d: dict) -> None:
                """In-place: keep only {{vars.X}} credential references, drop hardcoded UUIDs."""
                if "credentialId" in d:
                    v = d["credentialId"]
                    if not (isinstance(v, str) and v.startswith("{{vars.")):
                        d.pop("credentialId")
                if "credentialIds" in d:
                    kept = {k: v for k, v in d["credentialIds"].items()
                            if isinstance(v, str) and v.startswith("{{vars.")}
                    if kept:
                        d["credentialIds"] = kept
                    else:
                        d.pop("credentialIds")

            for node in workflow_data.get("nodes", []):
                node.pop("disabled", None)
                data = node.get("data", {})
                data.pop("disabled", None)
                _strip_credential_ids(data)
                config = node.get("config", {})
                _strip_credential_ids(config)
                for k in _strip_keys:
                    config.pop(k, None)
                if "config" in data:
                    _strip_credential_ids(data["config"])
                    for k in _strip_keys:
                        data["config"].pop(k, None)

        # Author-declared variables ride the fork, but per-user ones arrive
        # unfilled: the author's value (their repo, their channel) is exactly
        # what a new owner must replace, and an empty declared variable is what
        # the Setup tab turns into a question.
        fork_settings = dict(source.settings or {})
        _defs = fork_settings.get("variable_definitions")
        if isinstance(_defs, list):
            fork_settings["variable_definitions"] = [
                {**d, "value": ""} if isinstance(d, dict) and d.get("per_user") else d
                for d in _defs
            ]

        await repo.insert_forked_workflow(
            new_id=new_id,
            name=forked_name,
            description=source.description,
            workflow_data=workflow_data,
            owner_id=owner_id,
            org_id=org_id,
            settings=fork_settings,
            source_workflow_id=source_workflow_id,
            forked_by=user_id,
        )

        return ForkedResourceInfo(
            id=new_id,
            name=forked_name,
            resource_type="workflow",
            owner_id=owner_id,
            organization_id=org_id,
            forked_from_id=source.id,
            forked_from_name=source.name,
        )

    async def _fork_database(
        self,
        repo: ShareRepo,
        user_id: str,
        source_table_id: str,
        destination_type: str,
        destination_org_id: Optional[str],
        new_name: Optional[str],
        include_data: bool,
    ) -> Optional[ForkedResourceInfo]:
        """Fork a database table to a new location."""
        source = await repo.get_database_source(source_table_id)
        if not source:
            return None

        schema_rows = await repo.get_user_table_columns(source.id)

        # Generate new ID and names
        new_id = str(uuid.uuid4())
        forked_title = new_name or f"Copy of {source.title}"
        # Generate unique virtual table name
        base_virtual_name = source.virtual_table_name
        forked_virtual_name = f"{base_virtual_name}_copy_{uuid.uuid4().hex[:6]}"

        # owner_id is always the user who forked (databases require an owner)
        # org_id is set if forking to an organization
        owner_id = user_id
        org_id = destination_org_id if destination_type == "organization" else None

        # Build CREATE TABLE column defs from schema
        columns = []
        for row in schema_rows:
            col_def = f'"{row.column_name}" {row.data_type}'
            if row.column_name == "id":
                # Preserve SERIAL for id column (info schema shows it as integer)
                col_def = '"id" SERIAL PRIMARY KEY'
            else:
                if row.is_nullable == "NO":
                    col_def += " NOT NULL"
                if row.column_default:
                    # Skip nextval defaults (handled by SERIAL)
                    if "nextval" not in row.column_default:
                        col_def += f" DEFAULT {row.column_default}"
            columns.append(col_def)

        # Copy data columns exclude id (SERIAL generates new)
        copy_data_columns = (
            [row.column_name for row in schema_rows if row.column_name != "id"]
            if include_data else None
        )

        await repo.insert_forked_database(
            new_id=new_id,
            title=forked_title,
            description=source.description,
            virtual_table_name=forked_virtual_name,
            owner_id=owner_id,
            org_id=org_id,
            display_metadata=source.display_metadata,
            schema_definition=source.schema_definition,
            create_table_columns=columns,
            source_table_id=source.id,
            forked_by=user_id,
            copy_data_columns=copy_data_columns,
        )

        # Invalidate database cache so the new table appears
        _invalidate_database_cache(org_id)

        return ForkedResourceInfo(
            id=new_id,
            name=forked_title,
            resource_type="database",
            owner_id=owner_id,
            organization_id=org_id,
            forked_from_id=source.id,
            forked_from_name=source.title,
        )

    # =========================================================================
    # Workflow Template Methods (SEO-friendly template library)
    # =========================================================================








