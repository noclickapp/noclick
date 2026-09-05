"""
Credentials handler for managing encrypted user credentials.
Handles credential creation, listing, retrieval, updating, and deletion.
"""

import asyncio
import logging
from typing import Dict, Callable, List
from utils.webhook_manager import WebhookManager
from utils.database_pool import DatabasePoolMixin
from utils.encryption import get_encryption
from wss.handlers.workflow_handler import get_user_org_context
from nodes.oauth.google_oauth import revoke_token as revoke_google_token
from nodes.oauth.twitter_oauth import revoke_token as revoke_twitter_token
from nodes.oauth.klaviyo_oauth import revoke_token as revoke_klaviyo_token
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from utils.access_control import check_resource_access
from utils.credentials import (
    collect_node_credential_uuids,
    get_workflow_owner_id,
    authorize_credentials_for_workflow,
)
from repositories.credentials import CredentialsRepo
from wss.sender.responses import (
    CredentialInfo,
    CredentialListResponse,
    CredentialGetResponse,
    CredentialCreateResponse,
    CredentialUpdateResponse,
    CredentialDeleteResponse,
    CredentialRequestInfo,
    CredentialRequestCreateResponse,
    CredentialRequestListResponse,
    CredentialRequestCancelResponse,
)
from wss.receiver.client_events import (
    CredentialCreateRequest,
    CredentialListRequest,
    CredentialGetRequest,
    CredentialUpdateRequest,
    CredentialDeleteRequest,
    CredentialRequestCreateRequest,
    CredentialRequestListRequest,
    CredentialRequestCancelRequest,
    CredentialDisplayInfoRequest,
    CredentialAuthorizeForWorkflowRequest,
    CredentialValidateAccessRequest,
)

logger = logging.getLogger(__name__)


class CredentialsHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for credential operations with encryption"""

    def __init__(self, sio):
        super().__init__(sio)
        self.encryption = get_encryption()

    def get_events(self) -> Dict[str, Callable]:
        """Register credential operation events"""
        return {
            "credential:create": self.create_credential,
            "credential:list": self.list_credentials,
            "credential:get": self.get_credential,
            "credential:display_info": self.display_info,
            "credential:authorize_for_workflow": self.authorize_for_workflow,
            "credential:update": self.update_credential,
            "credential:delete": self.delete_credential,
            "credential:request:create": self.create_credential_request,
            "credential:request:list": self.list_credential_requests,
            "credential:request:cancel": self.cancel_credential_request,
            "credential:validate_access": self.validate_access,
        }

    async def setup_user(self, sid: str) -> None:
        """Kick off background ownership transfer for credentials provided
        via the request flow."""
        from utils.async_helpers import spawn
        spawn(
            self._transfer_provided_credentials(sid),
            name=f"credentials-transfer-provided:{sid}",
        )

    async def _transfer_provided_credentials(self, sid: str) -> None:
        """Transfer ownership of credentials that were provided via the
        credential request flow before this user had an account."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            user_email = session.get('user_data', {}).get('email')
            if not user_id or not user_email:
                return

            pool = await self.get_pool()
            if not pool:
                return

            repo = CredentialsRepo(pool)
            pending = await repo.list_pending_transfers(user_email)
            if not pending:
                return

            logger.info("[CredentialsHandler] Transferring %s provided credential(s)", len(pending))

            for row in pending:
                await repo.transfer_credential_ownership(
                    credential_id=row.credential_id,
                    new_owner_id=user_id,
                    requester_id=row.requester_id,
                )
                logger.info(f"[CredentialsHandler] Transferred credential {row.credential_id} ownership to {user_id}, shared with {row.requester_id}")

        except Exception as e:
            logger.error(f"[CredentialsHandler] Error transferring credential ownership for sid {sid}: {e}")

    async def create_credential(self, sid: str, request: CredentialCreateRequest) -> None:
        """Create a new encrypted credential"""
        try:
            # Get user session
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

            # Harness LLM API keys get a definitive live probe before they're
            # saved — a creditless/revoked key rejected HERE (in the form, with
            # the same message the runtime classifier uses) never becomes a
            # confusing mid-turn failure. Fails open on non-definitive signals.
            from nodes.agent.key_validation import validate_agent_api_key

            rejection = await validate_agent_api_key(
                request.credential_type, request.credential_data
            )
            if rejection:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=rejection
                ))
                return

            # Encrypt the credential data
            try:
                encrypted_data = self.encryption.encrypt_credential(request.credential_data)
            except Exception as e:
                logger.error(f"[CredentialsHandler] Encryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Failed to encrypt credential"
                ))
                return

            async with pool.acquire() as conn:
                from repositories.credentials import create_credential_with_limit_check
                user_tier = session.get('user_data', {}).get('subscription_tier', 'free')
                row, error = await create_credential_with_limit_check(
                    conn, user_id, user_tier, request.credential_type,
                    request.name, encrypted_data, request.metadata or {},
                )
                if error:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error=error
                    ))
                    if error.startswith('Plan limit reached:'):
                        from utils.capabilities import PLAN_GATE_ALERT, capability
                        alert_plan_gate = capability(PLAN_GATE_ALERT)
                        if alert_plan_gate is not None:
                            alert_plan_gate(
                                session.get('user_data', {}), "Credential Limit Hit",
                                {"Type": request.credential_type},
                            )
                    return

                # Build credential info
                credential = CredentialInfo(
                    id=str(row['id']),
                    name=row['name'],
                    credential_type=row['credential_type'],
                    metadata=row['metadata'],
                    created_at=row['created_at'].isoformat(),
                    updated_at=row['updated_at'].isoformat()
                )

                # Send success response
                response = CredentialCreateResponse(
                    success=True,
                    credential=credential,
                    message="Credential created successfully"
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                logger.info(f"[CredentialsHandler] Created credential {row['id']} for user {user_id}")

        except Exception as e:
            logger.error(f"[CredentialsHandler] Error creating credential: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error="Internal error"
            ))

    async def list_credentials(self, sid: str, request: CredentialListRequest) -> None:
        """List all credentials accessible to the current user (without decrypted data)"""
        try:
            # Get user session
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

            repo = CredentialsRepo(pool)

            # ``get_user_org_context`` and ``get_context_tier`` both take an
            # explicit ``conn`` — the repo owns its own SQL, not theirs — so we
            # borrow one connection to run both. The main list query runs on a
            # separate acquire inside ``repo.list_accessible``.
            from billing.plan_limits import get_context_tier, get_limit
            async with pool.acquire() as conn:
                org_id = await get_user_org_context(conn, user_id)
                tier = await get_context_tier(conn, user_id)

            # Fetch all credentials the user can access:
            # 1. Credentials they own (personal + org where they're owner)
            # 2. Credentials shared with them directly
            # 3. Credentials shared with their current org (only when in org context)
            accessible = await repo.list_accessible(user_id, org_id)

            # Sort by sort_order (owner-first) then created_at desc — same as
            # the pre-migration Python re-sort on top of the SQL DISTINCT ON.
            accessible = sorted(
                accessible,
                key=lambda r: (r.sort_order, -r.created_at.timestamp()),
            )

            # Enforce credential cap per type within the current context.
            # In org context: only org credentials (owned by org + shared with org) count against the org cap.
            # Personal credentials are visible but don't count against the org limit.
            # In personal context: owned + shared credentials count against the personal cap.
            hidden_shared_count = 0
            over_cap_ids: set[str] = set()
            cap = get_limit(tier, 'credentials_per_type')
            if cap is not None:
                org_id_str = str(org_id) if org_id else None
                # Separate rows into: context-relevant (count against cap) vs personal (always shown)
                # In org context, a credential is "personal" (uncapped) only if it's owned by the
                # user, belongs to a different org, AND was NOT shared with the current org.
                # Credentials shared with the org always count against the org's cap.
                capped_rows = []
                uncapped_rows = []
                for r in accessible:
                    r_org_id = r.organization_id
                    is_own_personal = (r.owner_id == user_id and r_org_id != org_id_str)
                    if org_id_str and is_own_personal and not r.shared_with_org:
                        # User's own personal credential visible in org context and NOT shared with org
                        uncapped_rows.append(r)
                    else:
                        capped_rows.append(r)

                # Two-pass algorithm to mark credentials that exceed the per-type cap.
                #
                # Why two passes: user's own credentials get priority — they fill
                # cap slots first. Shared credentials from others only fill leftover
                # slots. Any credential (own or shared) beyond the cap is marked
                # over_cap so the frontend can hide it from the dropdown.
                #
                # First step: count the user's own credentials per type. Mark excess as over_cap.
                #   e.g. free cap=1, user owns 2 google_oauth → second one is over_cap.
                own_type_counts: dict[str, int] = {}
                for r in capped_rows:
                    if r.owner_id == user_id:
                        ct = r.credential_type
                        own_type_counts[ct] = own_type_counts.get(ct, 0) + 1
                        if own_type_counts[ct] > cap:
                            over_cap_ids.add(r.id)
                # Second step: fill remaining slots with others' shared credentials.
                #   hidden_shared_count tracks how many *shared* credentials are
                #   hidden (shown as "N hidden credentials" in the frontend).
                #   User's own over-cap credentials are NOT counted here since
                #   they aren't "hidden shared" — they're just the user's excess.
                type_counts: dict[str, int] = dict(own_type_counts)
                for r in capped_rows:
                    if r.owner_id != user_id:
                        ct = r.credential_type
                        type_counts[ct] = type_counts.get(ct, 0) + 1
                        if type_counts[ct] > cap:
                            over_cap_ids.add(r.id)
                            hidden_shared_count += 1
                accessible = uncapped_rows + capped_rows

            # Live provider-session state for connection-backed rows — a dead
            # session kills the credential silently, so the picker must flag it.
            # Rows absent from the health map are unknown, never dead.
            from utils.credential_health import get_credential_health
            health = await get_credential_health(accessible)

            credentials = []
            for row in accessible:
                is_shared = row.access_type in ('shared', 'shared_org')
                row_health = health.get(str(row.id))
                credentials.append(CredentialInfo(
                    id=row.id,
                    name=row.name,
                    credential_type=row.credential_type,
                    metadata=row.metadata,
                    created_at=row.created_at.isoformat(),
                    updated_at=row.updated_at.isoformat(),
                    access_type=row.access_type,
                    organization_id=row.organization_id,
                    shared_with_org=row.shared_with_org,
                    over_cap=row.id in over_cap_ids,
                    shared_by_email=row.owner_email if is_shared else None,
                    shared_by_name=row.owner_name if is_shared else None,
                    share_id=row.share_id if is_shared else None,
                    revoked_at=row.revoked_at.isoformat() if row.revoked_at else None,
                    revoked_reason=row.revoked_reason,
                    connection_status=row_health.status if row_health else None,
                    connection_healthy=row_health.healthy if row_health else None,
                    connection_hint=row_health.hint if row_health else None,
                ))

            response = CredentialListResponse(
                credentials=[c.model_dump() for c in credentials],
                hidden_shared_count=hidden_shared_count,
                subscription_tier=tier,
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[CredentialsHandler] Listed {len(credentials)} credentials for user {user_id} (hidden_shared={hidden_shared_count})")

        except Exception as e:
            logger.error(f"[CredentialsHandler] Error listing credentials: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error="Internal error"
            ))

    async def display_info(self, sid: str, request: CredentialDisplayInfoRequest) -> None:
        """Display-only metadata (name, type, owner) for the credentials a workflow's
        nodes reference. Gated by workflow access. Returns NO secret and grants NO
        access — it just lets collaborators SEE the name + owner of credentials the
        flow uses (which are resolved as the owner at execution, not shared into the
        collaborator's account)."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="User not authenticated"))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="Database connection not available"))
                return

            # Access check still needs a conn (check_resource_access takes one).
            # Everything else routes through the repo.
            async with pool.acquire() as conn:
                access = await check_resource_access(conn, user_id, "workflow", request.workflow_id)
                if not access.has_access:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id, data={}, error="You don't have access to this workflow"))
                    return

            repo = CredentialsRepo(pool)
            wf = await repo.fetch_workflow_owner_and_blob(request.workflow_id)
            cred_ids = list(collect_node_credential_uuids(wf.workflow)) if wf else []
            credentials = []
            if cred_ids and wf:
                # Constrain to credentials owned by the WORKFLOW OWNER. Without this
                # a collaborator could inject any credential UUID into the blob and
                # read back a third party's credential name + owner identity. The
                # display path only ever needs the owner's creds (a collaborator's
                # own creds come from their credential:list).
                rows = await repo.fetch_credentials_display_info(cred_ids, wf.owner_id)
                for r in rows:
                    owned_by_me = r.owner_id == user_id
                    owner_label = None
                    if not owned_by_me:
                        owner_label = r.owner_name or (
                            r.owner_email.split('@')[0] if r.owner_email else None)
                    credentials.append({
                        "id": r.id,
                        "name": r.name,
                        "credential_type": r.credential_type,
                        "owned_by_me": owned_by_me,
                        "owner_name": owner_label,  # display only when NOT owned by the requester
                    })

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={"credentials": credentials}))

        except Exception as e:
            logger.error(f"[CredentialsHandler] Error getting credential display info: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error="Internal error"))

    async def authorize_for_workflow(self, sid: str, request: CredentialAuthorizeForWorkflowRequest) -> None:
        """Authorize a credential for run-as-owner resolution on a workflow.

        This is the ONLY trusted authorization signal for the collaborative frontend.
        It is OWNER-GATED: only the workflow owner can authorize, and only a credential
        the owner actually owns. A collaborator's call is a silent no-op — they cannot
        introduce an owner credential into the authorized set by placing a credentialId
        on a node (which they can do via the presence channel). Server-attributed paths
        (SDK set_node_config, MCP, internal builder) authorize inline at write time."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="User not authenticated"))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={}, error="Database connection not available"))
                return

            owner_id = await get_workflow_owner_id(pool, request.workflow_id)
            # Owner-gated: silently no-op for non-owners. Returning success (without
            # authorizing) keeps the collaborative path quiet — the collaborator's
            # placement still syncs/persists, it just can't self-authorize a run.
            if not owner_id or str(owner_id) != str(user_id):
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={"authorized": False}))
                return

            # The owner must actually own the credential they're authorizing (a
            # lightweight ownership check — no decrypt). Authorizing a non-owned
            # credential would be inert anyway (run-as-owner resolution checks
            # ownership), but this keeps the authorized set clean.
            repo = CredentialsRepo(pool)
            if not await repo.is_owner(request.credential_id, owner_id):
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id, data={"authorized": False}))
                return

            # ``authorize_credentials_for_workflow`` takes an explicit conn — its
            # SQL lives outside this handler's domain (utils.credentials owns it)
            # so we borrow one connection here rather than pulling it into the repo.
            async with pool.acquire() as conn:
                await authorize_credentials_for_workflow(
                    conn, request.workflow_id, owner_id, [request.credential_id])

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={"authorized": True}))

        except Exception as e:
            logger.error(f"[CredentialsHandler] Error authorizing credential for workflow: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id, data={}, error="Internal error"))

    async def get_credential(self, sid: str, request: CredentialGetRequest) -> None:
        """Get a specific credential with decrypted data (requires at least view permission)"""
        try:
            # Get user session
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

            async with pool.acquire() as conn:
                org_id = await get_user_org_context(conn, user_id)

            repo = CredentialsRepo(pool)
            # Fetch credential if user has access (owner, user share, or org share in current context)
            row = await repo.fetch_with_access(request.credential_id, user_id, org_id)

            if not row:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Credential not found or access denied"
                ))
                return

            # Decrypt the credential data
            try:
                credential_data = self.encryption.decrypt_credential(row.credential)
            except Exception as e:
                logger.error(f"[CredentialsHandler] Decryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Failed to decrypt credential"
                ))
                return

            response = CredentialGetResponse(
                credential_id=row.id,
                name=row.name,
                credential_type=row.credential_type,
                credential_data=credential_data,
                metadata=row.metadata
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[CredentialsHandler] Retrieved credential {row.id} for user {user_id}")

        except Exception as e:
            logger.error(f"[CredentialsHandler] Error getting credential: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error="Internal error"
            ))

    async def update_credential(self, sid: str, request: CredentialUpdateRequest) -> None:
        """Update a credential (requires edit permission)"""
        try:
            # Get user session
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

            async with pool.acquire() as conn:
                org_id = await get_user_org_context(conn, user_id)

            repo = CredentialsRepo(pool)
            # Check if user has edit permission (owner, user share with edit, or org share with edit in current context)
            if not await repo.has_edit_permission(request.credential_id, user_id, org_id):
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Credential not found or you don't have edit permission"
                ))
                return

            if (
                request.name is None
                and request.credential_data is None
                and request.metadata is None
            ):
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="No fields to update"
                ))
                return

            # Replacing the secret blob goes through the credentials write
            # choke point: it encrypts, bumps the CAS token_version, and clears
            # revoked_at — user-entered new secrets are the recovery path for
            # an auto-revoked credential. Name/metadata-only edits keep the
            # direct UPDATE (they never touch the blob).
            if request.credential_data is not None:
                from utils.credentials import update_credential_data

                updated = await update_credential_data(
                    credential_id=request.credential_id,
                    user_id=user_id,
                    new_data=request.credential_data,
                    metadata_updates=request.metadata,
                    pool=pool,
                )
                if not updated:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Failed to update credential"
                    ))
                    return

            # Metadata is only re-applied here when the secret blob was NOT
            # replaced — the credential_data path already merged it inside
            # update_credential_data.
            metadata_update = request.metadata if request.credential_data is None else None
            row = await repo.update_metadata_or_fetch(
                request.credential_id,
                name=request.name,
                metadata=metadata_update,
            )

            if not row:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Credential not found or access denied"
                ))
                return

            credential = CredentialInfo(
                id=row.id,
                name=row.name,
                credential_type=row.credential_type,
                metadata=row.metadata,
                created_at=row.created_at.isoformat(),
                updated_at=row.updated_at.isoformat()
            )

            response = CredentialUpdateResponse(
                success=True,
                credential=credential,
                message="Credential updated successfully"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[CredentialsHandler] Updated credential {row.id} for user {user_id}")

        except Exception as e:
            logger.error(f"[CredentialsHandler] Error updating credential: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error="Internal error"
            ))

    async def delete_credential(self, sid: str, request: CredentialDeleteRequest) -> None:
        """Delete a credential (owner only)"""
        try:
            # Get user session
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

            repo = CredentialsRepo(pool)
            # Owner-only: fetch credential data for revocation, gated on ownership.
            row = await repo.fetch_for_delete_as_owner(request.credential_id, user_id)

            if not row:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error=(
                        "Only the owner can delete this credential. "
                        "Remove it from your list instead."
                    )
                ))
                return

            # Surface which workflows still reference this credential. Without
            # confirm this is a dry run: the FE shows the list in its confirm
            # dialog and re-sends with confirm=true.
            affected = await repo.list_workflows_referencing_credential(
                request.credential_id, user_id, row.organization_id
            )
            if not request.confirm:
                response = CredentialDeleteResponse(
                    success=True,
                    message="Dry run — nothing deleted",
                    credential_id=request.credential_id,
                    deleted=False,
                    affected_workflows=affected,
                )
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=response.model_dump()
                ))
                return

            # Deregister trigger webhooks registered under this credential
            # BEFORE token revocation and row deletion — provider teardown
            # needs the still-valid credential. Runs inline (not backgrounded)
            # because ordering against the hard delete is load-bearing;
            # failures are logged and the delete proceeds (the deactivated row
            # 410s deliveries either way).
            webhook_nodes = await repo.list_active_webhook_nodes_for_credential(
                request.credential_id
            )
            nodes_by_workflow: Dict[str, List[str]] = {}
            for ref in webhook_nodes:
                nodes_by_workflow.setdefault(ref["workflow_id"], []).append(ref["node_id"])
            for wf_id, node_ids in nodes_by_workflow.items():
                try:
                    await WebhookManager.deregister_node_webhooks(
                        pool, wf_id, node_ids, requesting_user_id=user_id,
                    )
                except Exception as e:
                    logger.error(
                        f"[CredentialsHandler] Webhook deregistration failed for "
                        f"workflow {wf_id} nodes {node_ids} during credential delete: {e}"
                    )

            # If it's a Google OAuth credential, revoke the token with Google
            credential_type = row.credential_type
            if credential_type and credential_type.startswith('google'):
                try:
                    encryption = get_encryption()
                    cred_data = encryption.decrypt_credential(row.credential)

                    # Revoke refresh token (this also invalidates access tokens)
                    if 'refresh_token' in cred_data:
                        await revoke_google_token(cred_data['refresh_token'])
                        logger.info(f"[CredentialsHandler] Revoked Google token for credential {request.credential_id}")
                except Exception as e:
                    # Log but don't fail - still delete the credential
                    logger.warning(f"[CredentialsHandler] Failed to revoke Google token: {e}")

            # If it's a Twitter OAuth credential, revoke the token with X
            if credential_type == 'twitter_oauth':
                try:
                    encryption = get_encryption()
                    cred_data = encryption.decrypt_credential(row.credential)

                    # Revoke refresh token (also invalidates associated access tokens)
                    if 'refresh_token' in cred_data and cred_data['refresh_token']:
                        await revoke_twitter_token(
                            cred_data['refresh_token'],
                            token_type_hint="refresh_token",
                            client_id=cred_data.get('client_id'),
                            client_secret=cred_data.get('client_secret'),
                        )
                        logger.info(f"[CredentialsHandler] Revoked Twitter token for credential {request.credential_id}")
                except Exception as e:
                    # Log but don't fail - still delete the credential
                    logger.warning(f"[CredentialsHandler] Failed to revoke Twitter token: {e}")

            # If it's a Klaviyo OAuth credential, revoke the token so the app no
            # longer shows as installed on Klaviyo's side (marketplace uninstall).
            if credential_type == 'klaviyo_oauth':
                try:
                    encryption = get_encryption()
                    cred_data = encryption.decrypt_credential(row.credential)

                    # Revoking the refresh token invalidates the whole grant.
                    if cred_data.get('refresh_token'):
                        await revoke_klaviyo_token(
                            cred_data['refresh_token'],
                            token_type_hint="refresh_token",
                            client_id=cred_data.get('client_id'),
                            client_secret=cred_data.get('client_secret'),
                        )
                        logger.info(f"[CredentialsHandler] Revoked Klaviyo token for credential {request.credential_id}")
                except Exception as e:
                    # Log but don't fail - still delete the credential
                    logger.warning(f"[CredentialsHandler] Failed to revoke Klaviyo token: {e}")

            # If it's a WhatsApp QR credential, delete the WAHooks connection.
            # User-initiated deletion proceeds even if teardown fails (the
            # daily orphan sweep reconciles), but the failure is an ERROR —
            # a live connection with no credential is billed AND still linked
            # to the user's personal WhatsApp.
            if credential_type == 'whatsapp_qr':
                try:
                    from utils.wahooks_connections import delete_wahooks_connection
                    encryption = get_encryption()
                    cred_data = encryption.decrypt_credential(row.credential)
                    connection_id = cred_data.get('connection_id')
                    if connection_id:
                        await delete_wahooks_connection(connection_id)
                except Exception as e:
                    logger.error(f"[CredentialsHandler] Failed to delete WAHooks connection: {e}")

            # Delete the credential and its shares (edit permission verified above).
            await repo.delete_credential_and_shares(request.credential_id)

            response = CredentialDeleteResponse(
                success=True,
                message="Credential deleted successfully",
                credential_id=request.credential_id
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[CredentialsHandler] Deleted credential {request.credential_id} for user {user_id}")

        except Exception as e:
            logger.error(f"[CredentialsHandler] Error deleting credential: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error="Internal error"
            ))

    # -------------------------------------------------------------------------
    # Credential Request operations (request credentials from external users)
    # -------------------------------------------------------------------------

    async def create_credential_request(self, sid: str, request: CredentialRequestCreateRequest) -> None:
        """Create a credential request. Emails the target when an address is
        given; otherwise returns a shareable link the requester copies and
        sends however they like."""
        from utils.email import credential_provide_url, send_credential_request_email

        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            user_data = session.get('user_data', {})

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

            # Empty email → shareable copy-link request (no email sent). The
            # column is NOT NULL, so link-mode rows store an empty target_email.
            target_email = (request.target_email or "").strip()

            # Upsert: re-sending a request refreshes the token and expiration
            repo = CredentialsRepo(pool)
            row = await repo.upsert_credential_request(
                requester_id=user_id,
                target_email=target_email,
                credential_type=request.credential_type,
                message=request.message,
            )

            if not row:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Failed to create credential request"
                ))
                return

            # Email the target only when an address was provided
            if target_email:
                requester_email = user_data.get('email', '')
                requester_name = user_data.get('user_metadata', {}).get('name', requester_email.split('@')[0] if requester_email else 'Someone')

                await send_credential_request_email(
                    to_email=target_email,
                    requester_name=requester_name,
                    credential_type=request.credential_type,
                    token=row.token,
                    message=request.message,
                    frontend_url=request.frontend_url,
                )

            req_info = CredentialRequestInfo(
                id=row.id,
                target_email=row.target_email,
                credential_type=row.credential_type,
                message=row.message,
                status=row.status,
                expires_at=row.expires_at.isoformat() if row.expires_at else None,
                created_at=row.created_at.isoformat(),
                fulfilled_at=row.fulfilled_at.isoformat() if row.fulfilled_at else None,
            )

            response = CredentialRequestCreateResponse(
                success=True,
                request=req_info,
                provide_url=credential_provide_url(row.token, request.frontend_url),
                message="Credential request sent" if target_email else "Credential request link created"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[CredentialsHandler] Created credential request ({'email' if target_email else 'link'}) for {request.credential_type} by user {user_id}")

        except Exception as e:
            logger.error(f"[CredentialsHandler] Error creating credential request: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error="Internal error"
            ))

    async def list_credential_requests(self, sid: str, request: CredentialRequestListRequest) -> None:
        """List all outgoing credential requests for the current user."""
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

            repo = CredentialsRepo(pool)
            rows = await repo.list_credential_requests(user_id)

            requests_list = [
                CredentialRequestInfo(
                    id=row.id,
                    target_email=row.target_email,
                    credential_type=row.credential_type,
                    message=row.message,
                    status=row.status,
                    credential_id=row.credential_id,
                    expires_at=row.expires_at.isoformat() if row.expires_at else None,
                    created_at=row.created_at.isoformat(),
                    fulfilled_at=row.fulfilled_at.isoformat() if row.fulfilled_at else None,
                )
                for row in rows
            ]

            response = CredentialRequestListResponse(requests=requests_list)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))

        except Exception as e:
            logger.error(f"[CredentialsHandler] Error listing credential requests: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error="Internal error"
            ))

    async def cancel_credential_request(self, sid: str, request: CredentialRequestCancelRequest) -> None:
        """Cancel a pending credential request."""
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

            repo = CredentialsRepo(pool)
            cancelled = await repo.cancel_credential_request(
                request.credential_request_id, user_id,
            )
            if not cancelled:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="Request not found or already resolved"
                ))
                return

            response = CredentialRequestCancelResponse(
                success=True,
                message="Credential request cancelled"
            )
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response.model_dump()
            ))
            logger.info(f"[CredentialsHandler] Cancelled credential request {request.credential_request_id} for user {user_id}")

        except Exception as e:
            logger.error(f"[CredentialsHandler] Error cancelling credential request: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error="Internal error"
            ))

    async def validate_access(self, sid: str, request: CredentialValidateAccessRequest) -> None:
        """Post-connect API access validation — runs the node class's validate_credential_access hook."""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')
            if not user_id:
                return

            pool = await self.get_pool()
            if not pool:
                return

            from nodes.core.registry import NODE_REGISTRY
            node_class = NODE_REGISTRY.get(request.node_type)
            validate_fn = getattr(node_class, "validate_credential_access", None) if node_class else None
            if not validate_fn:
                # Node doesn't implement validation — report valid so the UI isn't blocked.
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={"valid": True},
                ))
                return

            async with pool.acquire() as conn:
                org_id = await get_user_org_context(conn, user_id)

            repo = CredentialsRepo(pool)
            row = await repo.fetch_with_access(request.credential_id, user_id, org_id)
            if not row:
                return

            try:
                credential_data = self.encryption.decrypt_credential(row.credential)
            except Exception as e:
                logger.error(f"[CredentialsHandler] validate_access: decryption failed: {e}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={"valid": False, "error": "Failed to decrypt credential"},
                ))
                return

            try:
                result = await validate_fn(credential_data)
            except Exception as e:
                result = {"valid": False, "error": str(e)}

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=result,
            ))

        except Exception as e:
            logger.error(f"[CredentialsHandler] validate_access error: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={"valid": False, "error": "Internal error"},
            ))
