"""
Organization handler for managing organizations, members, invites, and SSO configuration.
Enables enterprise features including SAML SSO, role-based access control, and org-level billing.
"""

import logging
import re
import os
import base64
import httpx
from typing import Dict, Callable, Optional
from uuid import UUID, uuid4

from utils.database_pool import DatabasePoolMixin
from utils.supabase_admin import get_supabase_admin, SupabaseAdminError
from utils.email import send_organization_invite_email
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from billing.plan_limits import check_organization_limit
from repositories.organization import OrgRepo

logger = logging.getLogger(__name__)

# Supabase Storage config
ORG_ICONS_BUCKET = 'organization-icons'


class OrganizationHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for organization management operations"""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        """Register organization operation events"""
        return {
            "organization:create": self.create_organization,
            "organization:get": self.get_organization,
            "organization:update": self.update_organization,
            "organization:delete": self.delete_organization,
            "organization:list_mine": self.list_my_organizations,
            "organization:switch": self.switch_organization,
            "organization:upload_icon": self.upload_icon,
            "organization:members:list": self.list_members,
            "organization:members:invite": self.invite_member,
            "organization:members:remove": self.remove_member,
            "organization:members:update_role": self.update_member_role,
            "organization:transfer_ownership": self.transfer_ownership,
            "organization:invites:list": self.list_invites,
            "organization:invites:get": self.get_invite_details,
            "organization:invites:accept": self.accept_invite,
            "organization:invites:revoke": self.revoke_invite,
            "organization:sso:configure": self.configure_sso,
            "organization:sso:disable": self.disable_sso,
            "organization:sso:info": self.get_sso_info,
            "organization:check_slug": self.check_slug,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    def _generate_slug(self, name: str) -> str:
        """Generate a URL-friendly slug from organization name"""
        slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        if not slug:
            slug = 'org'
        return slug

    def _validate_slug(self, slug: str) -> tuple[bool, str]:
        """Validate slug format. Returns (is_valid, error_message)"""
        if not slug:
            return False, "Slug is required"
        if len(slug) < 2:
            return False, "Slug must be at least 2 characters"
        if len(slug) > 50:
            return False, "Slug must be 50 characters or less"
        if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$', slug) and not re.match(r'^[a-z0-9]$', slug):
            return False, "Slug must contain only lowercase letters, numbers, and hyphens (cannot start or end with hyphen)"
        return True, ""

    async def _get_user_org_membership(self, conn, user_id: str, organization_id: UUID) -> Optional[dict]:
        """Get user's membership record for an organization"""
        repo = OrgRepo(await self.get_pool())
        return await repo.get_membership(conn, user_id, organization_id)

    async def _is_admin_or_owner(self, conn, user_id: str, organization_id: UUID) -> bool:
        """Check if user is admin or owner of organization"""
        repo = OrgRepo(await self.get_pool())
        return await repo.is_admin_or_owner(conn, user_id, organization_id)

    def _get_member_limit(self, tier: str) -> Optional[int]:
        """Get member limit based on subscription tier"""
        limits = {
            'free': 3,
            'plus': 3,
            'pro': 5,
            'enterprise': None,  # Unlimited
        }
        return limits.get(tier, 3)  # Default to free tier limit

    async def _check_member_limit(self, conn, organization_id: UUID) -> tuple[bool, Optional[str]]:
        """Check if organization can add more members.
        Counts both current members AND pending invites to prevent over-inviting.
        For personal workspace orgs, uses user_billing.subscription_tier.
        Returns (can_add, error_message)
        """
        repo = OrgRepo(await self.get_pool())
        row = await repo.get_member_limit_stats(conn, organization_id)

        if not row:
            logger.warning(f"[MEMBER_LIMIT] Organization {organization_id} not found")
            return False, "Organization not found"

        tier = row['subscription_tier']

        # For personal workspace orgs, use the owner's personal tier instead
        if row['is_personal_workspace']:
            owner_tier = await repo.get_personal_workspace_owner_tier(conn, organization_id)
            if owner_tier is not None:
                tier = owner_tier
        member_count = row['member_count']
        pending_invite_count = row['pending_invite_count']
        total_count = member_count + pending_invite_count
        limit = self._get_member_limit(tier)

        logger.info(f"[MEMBER_LIMIT] Org {organization_id}: tier={tier}, members={member_count}, pending_invites={pending_invite_count}, total={total_count}, limit={limit}")

        # Unlimited for enterprise
        if limit is None:
            return True, None

        if total_count >= limit:
            return False, f"Organization member limit reached. {tier.capitalize()} plan allows up to {limit} members. Please upgrade to add more members."

        return True, None

    async def create_organization(self, sid: str, data: dict) -> None:
        """Create a new organization with the current user as owner"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            name = data.get('name')
            if not name:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization name is required"
                ))
                return

            # Get optional custom slug
            custom_slug = data.get('slug')
            if custom_slug:
                custom_slug = custom_slug.strip().lower()
                is_valid, error_msg = self._validate_slug(custom_slug)
                if not is_valid:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error=error_msg
                    ))
                    return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Check org creation limit based on personal tier
                can_create, limit_error = await check_organization_limit(conn, UUID(user_id))
                if not can_create:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error=limit_error
                    ))
                    return

                # If custom slug provided, check if it's available
                if custom_slug:
                    if await repo.slug_taken(conn, custom_slug):
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request_id,
                            data={},
                            error="This slug is already taken"
                        ))
                        return
                    slug = custom_slug
                else:
                    # Generate unique slug from name
                    slug = await repo.find_unique_slug(conn, self._generate_slug(name))

                # All-or-nothing: an org row must never land without its owner
                # membership, primary-context switch, and billing pointer.
                async with conn.transaction():
                    org_row = await repo.insert_organization(
                        conn, name, slug, data.get('settings', {})
                    )

                    if not org_row:
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request_id,
                            data={},
                            error="Failed to create organization"
                        ))
                        return

                    org_id = org_row['id']

                    # Switch user's primary context to the new org before inserting member record
                    await repo.clear_all_primary_for_user(conn, user_id)

                    # Add creator as owner and mark as primary context
                    await repo.insert_member(
                        conn, org_id, UUID(user_id),
                        role='owner', joined_via='creator', is_primary=True,
                    )

                    # Update user's billing to reference org
                    await repo.set_user_billing_org(conn, UUID(user_id), org_id)

            # Build response
            organization = {
                'id': str(org_row['id']),
                'name': org_row['name'],
                'slug': org_row['slug'],
                'subscription_tier': org_row['subscription_tier'],
                'sso_enabled': org_row['sso_enabled'],
                'sso_domain': org_row['sso_domain'],
                'created_at': org_row['created_at'].isoformat() if org_row['created_at'] else None,
                'updated_at': org_row['updated_at'].isoformat() if org_row['updated_at'] else None,
            }

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'success': True,
                    'organization': organization,
                    'message': 'Organization created successfully'
                }
            ))

        except Exception as e:
            logger.error(f"Error creating organization: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def get_organization(self, sid: str, data: dict) -> None:
        """Get organization details (user must be a member)"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            if not organization_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization ID is required"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify user is a member
                membership = await repo.get_membership(conn, user_id, UUID(organization_id))
                if not membership:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Organization not found or access denied"
                    ))
                    return

                # Get organization details
                org_row = await repo.get_organization(conn, UUID(organization_id))

                if not org_row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Organization not found"
                    ))
                    return

                # Get member count
                member_count = await repo.count_members(conn, UUID(organization_id))

            organization = {
                'id': str(org_row['id']),
                'name': org_row['name'],
                'slug': org_row['slug'],
                'subscription_tier': org_row['subscription_tier'],
                'sso_enabled': org_row['sso_enabled'],
                'sso_domain': org_row['sso_domain'],
                'sso_metadata_url': org_row['sso_metadata_url'],
                'settings': org_row['settings'] or {},
                'icon_url': org_row['icon_url'],
                'member_count': member_count,
                'user_role': membership['role'],
                'created_at': org_row['created_at'].isoformat() if org_row['created_at'] else None,
                'updated_at': org_row['updated_at'].isoformat() if org_row['updated_at'] else None,
            }

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={'organization': organization}
            ))

        except Exception as e:
            logger.error(f"Error getting organization: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def update_organization(self, sid: str, data: dict) -> None:
        """Update organization settings (admin/owner only)"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            if not organization_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization ID is required"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify user is admin or owner
                if not await repo.is_admin_or_owner(conn, user_id, UUID(organization_id)):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Unauthorized: Admin or owner role required"
                    ))
                    return

                # Collect allowlisted updates — repo enforces the column allowlist
                updates_payload = {k: data[k] for k in ('name', 'settings') if k in data}
                if not updates_payload:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="No updates specified"
                    ))
                    return

                org_row = await repo.update_organization(
                    conn, UUID(organization_id), updates_payload
                )

                if not org_row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Failed to update organization"
                    ))
                    return

            organization = {
                'id': str(org_row['id']),
                'name': org_row['name'],
                'slug': org_row['slug'],
                'subscription_tier': org_row['subscription_tier'],
                'sso_enabled': org_row['sso_enabled'],
                'sso_domain': org_row['sso_domain'],
                'settings': org_row['settings'] or {},
                'created_at': org_row['created_at'].isoformat() if org_row['created_at'] else None,
                'updated_at': org_row['updated_at'].isoformat() if org_row['updated_at'] else None,
            }

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'success': True,
                    'organization': organization,
                    'message': 'Organization updated successfully'
                }
            ))

        except Exception as e:
            logger.error(f"Error updating organization: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def delete_organization(self, sid: str, data: dict) -> None:
        """Delete an organization (owner only)"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            if not organization_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization ID is required"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify user is owner
                membership = await repo.get_membership(conn, user_id, UUID(organization_id))
                if not membership or membership['role'] != 'owner':
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Unauthorized: Owner role required"
                    ))
                    return

                # Get SSO provider ID and icon URL before deletion
                org_row = await repo.get_organization_sso_and_icon(conn, UUID(organization_id))

                # Delete SSO provider in Supabase if configured
                if org_row and org_row['sso_provider_id']:
                    try:
                        supabase_admin = get_supabase_admin()
                        await supabase_admin.delete_sso_provider(org_row['sso_provider_id'])
                    except SupabaseAdminError as e:
                        logger.warning(f"Failed to delete SSO provider: {e}")

                # Delete organization icon from storage if it exists
                if org_row and org_row['icon_url']:
                    try:
                        supabase_url = os.getenv('SUPABASE_URL', '').rstrip('/')
                        supabase_secret_key = os.getenv('SUPABASE_SECRET_KEY', '')
                        if supabase_url and supabase_secret_key:
                            public_prefix = f"/storage/v1/object/public/{ORG_ICONS_BUCKET}/"
                            if public_prefix in org_row['icon_url']:
                                icon_path = org_row['icon_url'].split(public_prefix)[-1]
                                delete_url = f"{supabase_url}/storage/v1/object/{ORG_ICONS_BUCKET}/{icon_path}"
                                async with httpx.AsyncClient() as client:
                                    delete_response = await client.delete(
                                        delete_url,
                                        headers={'apikey': supabase_secret_key}
                                    )
                                    if delete_response.status_code not in (200, 204, 404):
                                        logger.warning(f"Failed to delete org icon: {delete_response.status_code}")
                    except Exception as e:
                        logger.warning(f"Error deleting org icon: {e}")

                # Delete organization (cascades to members and invites)
                result = await repo.delete_organization(conn, UUID(organization_id))

                if result == "DELETE 0":
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Organization not found"
                    ))
                    return

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'success': True,
                    'message': 'Organization deleted successfully'
                }
            ))

        except Exception as e:
            logger.error(f"Error deleting organization: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def transfer_ownership(self, sid: str, data: dict) -> None:
        """Transfer organization ownership to another member (owner only)"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            target_user_id = data.get('user_id')

            if not organization_id or not target_user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization ID and target user ID are required"
                ))
                return

            if user_id == target_user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Cannot transfer ownership to yourself"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify caller is owner
                membership = await repo.get_membership(conn, user_id, UUID(organization_id))
                if not membership or membership['role'] != 'owner':
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Unauthorized: Owner role required"
                    ))
                    return

                # Verify target is an accepted member
                target_membership = await repo.get_membership(conn, target_user_id, UUID(organization_id))
                if not target_membership:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Target user is not a member of this organization"
                    ))
                    return

                # Atomic swap via single CTE statement (see repo docstring).
                await repo.transfer_ownership(
                    conn, UUID(organization_id), UUID(user_id), UUID(target_user_id)
                )

            # Invalidate billing cache so charges route to new owner
            from billing.usage_tracker import ORG_OWNER_CACHE
            ORG_OWNER_CACHE.pop(organization_id, None)

            logger.info(f"Ownership transferred for org {organization_id}: {user_id} -> {target_user_id}")

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'success': True,
                    'message': 'Ownership transferred successfully'
                }
            ))

        except Exception as e:
            logger.error(f"Error transferring ownership: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def list_members(self, sid: str, data: dict) -> None:
        """List organization members"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            if not organization_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization ID is required"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify user is a member
                membership = await repo.get_membership(conn, user_id, UUID(organization_id))
                if not membership:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Organization not found or access denied"
                    ))
                    return

                # Get members with user info
                rows = await repo.list_members(conn, UUID(organization_id))

            members = []
            for row in rows:
                user_meta = row['raw_user_meta_data'] or {}
                # Check for full_name at top level, then in custom_claims (for SSO users)
                custom_claims = user_meta.get('custom_claims', {})
                full_name = user_meta.get('full_name') or user_meta.get('name')
                if not full_name and custom_claims:
                    # SSO providers store first_name/last_name in custom_claims
                    first_name = custom_claims.get('first_name', '')
                    last_name = custom_claims.get('last_name', '')
                    if first_name or last_name:
                        full_name = f"{first_name} {last_name}".strip()
                members.append({
                    'id': str(row['id']),
                    'user_id': str(row['user_id']),
                    'email': row['email'],
                    'full_name': full_name,
                    'username': user_meta.get('username'),
                    'avatar_url': user_meta.get('avatar_url'),
                    'role': row['role'],
                    'joined_via': row['joined_via'],
                    'joined_at': row['created_at'].isoformat() if row['created_at'] else None,
                })

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={'members': members}
            ))

        except Exception as e:
            logger.error(f"Error listing members: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def invite_member(self, sid: str, data: dict) -> None:
        """Invite a user to the organization (admin/owner only)"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            email = data.get('email')
            role = data.get('role', 'member')
            frontend_url = data.get('frontend_url')  # Dynamic URL for invite link

            if not organization_id or not email:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization ID and email are required"
                ))
                return

            if role not in ('admin', 'member'):
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Invalid role. Must be 'admin' or 'member'"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify user is admin or owner
                if not await repo.is_admin_or_owner(conn, user_id, UUID(organization_id)):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Unauthorized: Admin or owner role required"
                    ))
                    return

                # Check if user is already a member
                if await repo.is_member_by_email(conn, UUID(organization_id), email):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="User is already a member of this organization"
                    ))
                    return

                # Check member limit before creating invite
                can_add, limit_error = await self._check_member_limit(conn, UUID(organization_id))
                logger.info(f"[INVITE] Member limit check for org {organization_id}: can_add={can_add}, error={limit_error}")
                if not can_add:
                    logger.warning(f"[INVITE] Member limit reached for org {organization_id}: {limit_error}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error=limit_error
                    ))
                    return

                # Get organization name and icon for email
                org_row = await repo.get_organization_name_and_icon(conn, UUID(organization_id))
                org_name = org_row['name'] if org_row else None
                org_icon_url = org_row['icon_url'] if org_row else None

                # Create invite (upsert to handle re-invites)
                invite_row = await repo.upsert_invite(
                    conn, UUID(organization_id), email, role, UUID(user_id)
                )

            invite = {
                'id': str(invite_row['id']),
                'email': invite_row['email'],
                'role': invite_row['role'],
                'token': invite_row['token'],
                'expires_at': invite_row['expires_at'].isoformat() if invite_row['expires_at'] else None,
                'created_at': invite_row['created_at'].isoformat() if invite_row['created_at'] else None,
            }

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'success': True,
                    'invite': invite,
                    'message': f'Invitation sent to {email}'
                }
            ))

            # Send invitation email
            inviter_email = session.get('user_data', {}).get('email', 'A team member')
            await send_organization_invite_email(
                to_email=email,
                organization_name=org_name or 'the organization',
                inviter_name=inviter_email.split('@')[0] if '@' in inviter_email else inviter_email,
                invite_token=invite_row['token'],
                role=role,
                organization_icon_url=org_icon_url,
                frontend_url=frontend_url
            )

        except Exception as e:
            logger.error(f"Error inviting member: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def remove_member(self, sid: str, data: dict) -> None:
        """Remove a member from the organization (admin/owner only, cannot remove owner)"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            target_user_id = data.get('user_id')

            if not organization_id or not target_user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization ID and user ID are required"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify user is admin or owner
                if not await repo.is_admin_or_owner(conn, user_id, UUID(organization_id)):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Unauthorized: Admin or owner role required"
                    ))
                    return

                # Check target user's role
                target_membership = await repo.get_membership(conn, target_user_id, UUID(organization_id))
                if not target_membership:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="User is not a member of this organization"
                    ))
                    return

                if target_membership['role'] == 'owner':
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Cannot remove the organization owner"
                    ))
                    return

                # All-or-nothing: membership removal, primary-context restore,
                # and the billing pointer clear must land together.
                async with conn.transaction():
                    await repo.delete_member(conn, UUID(organization_id), UUID(target_user_id))

                    # If removed member had this as their primary org, restore personal workspace as primary
                    await repo.restore_personal_primary_if_no_primary(conn, UUID(target_user_id))

                    # Clear org reference from user billing
                    await repo.clear_user_billing_org(
                        conn, UUID(target_user_id), UUID(organization_id)
                    )

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'success': True,
                    'message': 'Member removed successfully'
                }
            ))

        except Exception as e:
            logger.error(f"Error removing member: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def update_member_role(self, sid: str, data: dict) -> None:
        """Update a member's role (admin/owner only, cannot change owner)"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            target_user_id = data.get('user_id')
            new_role = data.get('role')

            if not organization_id or not target_user_id or not new_role:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization ID, user ID, and role are required"
                ))
                return

            if new_role not in ('admin', 'member'):
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Invalid role. Must be 'admin' or 'member'"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify user is admin or owner
                if not await repo.is_admin_or_owner(conn, user_id, UUID(organization_id)):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Unauthorized: Admin or owner role required"
                    ))
                    return

                # Check target user's current role
                target_membership = await repo.get_membership(conn, target_user_id, UUID(organization_id))
                if not target_membership:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="User is not a member of this organization"
                    ))
                    return

                if target_membership['role'] == 'owner':
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Cannot change the organization owner's role"
                    ))
                    return

                # Update role
                await repo.update_member_role(
                    conn, UUID(organization_id), UUID(target_user_id), new_role
                )

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'success': True,
                    'message': f'Member role updated to {new_role}'
                }
            ))

        except Exception as e:
            logger.error(f"Error updating member role: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def list_invites(self, sid: str, data: dict) -> None:
        """List pending invites for an organization"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            if not organization_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization ID is required"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify user is a member
                membership = await repo.get_membership(conn, user_id, UUID(organization_id))
                if not membership:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Organization not found or access denied"
                    ))
                    return

                # Get pending invites
                rows = await repo.list_pending_invites(conn, UUID(organization_id))

            invites = []
            for row in rows:
                invites.append({
                    'id': str(row['id']),
                    'email': row['email'],
                    'role': row['role'],
                    'expires_at': row['expires_at'].isoformat() if row['expires_at'] else None,
                    'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                })

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={'invites': invites}
            ))

        except Exception as e:
            logger.error(f"Error listing invites: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def get_invite_details(self, sid: str, data: dict) -> None:
        """Get details about an invite by token (without accepting it)"""
        request_id = data.get('request_id')
        try:
            token = data.get('token')
            if not token:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Invite token is required"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Get invite details with org and inviter info
                invite_row = await repo.get_invite_details_by_token(conn, token)

                if not invite_row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Invite not found"
                    ))
                    return

                # Check if expired
                if invite_row['accepted_at']:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="This invite has already been accepted"
                    ))
                    return

                from datetime import datetime, timezone
                if invite_row['expires_at'] and invite_row['expires_at'] < datetime.now(timezone.utc):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="This invite has expired"
                    ))
                    return

                # Extract inviter name from email
                inviter_email = invite_row['inviter_email'] or ''
                inviter_name = inviter_email.split('@')[0] if '@' in inviter_email else 'A team member'

                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={
                        'invite': {
                            'email': invite_row['email'],
                            'role': invite_row['role'],
                            'expires_at': invite_row['expires_at'].isoformat() if invite_row['expires_at'] else None,
                            'organization_id': str(invite_row['organization_id']),
                            'organization_name': invite_row['organization_name'],
                            'organization_icon_url': invite_row['organization_icon_url'],
                            'inviter_name': inviter_name,
                        }
                    }
                ))

        except Exception as e:
            logger.error(f"Error getting invite details: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def accept_invite(self, sid: str, data: dict) -> None:
        """Accept an organization invite"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            token = data.get('token')
            if not token:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Invite token is required"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Get invite and verify it's valid
                invite_row = await repo.get_invite_by_token(conn, token)

                if not invite_row:
                    logger.warning("[INVITE] Invalid or expired invite")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Invalid or expired invite"
                    ))
                    return

                invite_email = invite_row['email'].lower()
                logger.info("[INVITE] Found a valid organization invite")

                # Get user's email from session (auth.users isn't accessible from regular connection)
                user_email = session.get('user_data', {}).get('email', '').lower()

                if not user_email:
                    logger.error(f"[INVITE] Could not get user email from session for user_id={user_id}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Could not verify your email address. Please try logging in again."
                    ))
                    return


                if user_email != invite_email:
                    logger.warning("[INVITE] Invite address did not match the signed-in account")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error=f"This invite is for {invite_email}, but you're signed in as {user_email}"
                    ))
                    return

                # Check if already a member
                existing = await repo.existing_membership_id(
                    conn, invite_row['organization_id'], user_id
                )

                if existing:
                    logger.info("[INVITE] Signed-in account is already an organization member")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="You are already a member of this organization"
                    ))
                    return

                # Check member limit before adding
                can_add, limit_error = await self._check_member_limit(conn, invite_row['organization_id'])
                if not can_add:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error=limit_error
                    ))
                    return

                # All-or-nothing: primary-context switch, membership, invite
                # consumption, and billing pointer must land together.
                async with conn.transaction():
                    await repo.clear_all_primary_for_user(conn, user_id)

                    # Add user as member and mark as primary context
                    await repo.insert_member(
                        conn,
                        invite_row['organization_id'], UUID(user_id),
                        role=invite_row['role'], joined_via='invite',
                        is_primary=True,
                    )

                    # Mark invite as accepted
                    await repo.mark_invite_accepted(conn, invite_row['id'])

                    # Update user billing to reference org
                    await repo.set_user_billing_org(
                        conn, UUID(user_id), invite_row['organization_id']
                    )

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'success': True,
                    'organization_id': str(invite_row['organization_id']),
                    'organization_name': invite_row['org_name'],
                    'message': f"You have joined {invite_row['org_name']}"
                }
            ))

        except Exception as e:
            logger.error(f"Error accepting invite: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def revoke_invite(self, sid: str, data: dict) -> None:
        """Revoke a pending invite (admin/owner only)"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            invite_id = data.get('invite_id')

            if not organization_id or not invite_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization ID and invite ID are required"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify user is admin or owner
                if not await repo.is_admin_or_owner(conn, user_id, UUID(organization_id)):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Unauthorized: Admin or owner role required"
                    ))
                    return

                # Delete invite
                result = await repo.delete_invite(
                    conn, UUID(invite_id), UUID(organization_id)
                )

                if result == "DELETE 0":
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Invite not found"
                    ))
                    return

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'success': True,
                    'message': 'Invite revoked successfully'
                }
            ))

        except Exception as e:
            logger.error(f"Error revoking invite: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def configure_sso(self, sid: str, data: dict) -> None:
        """Configure SAML SSO for an organization (admin/owner only)"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            domain = data.get('domain')  # Optional - will use slug if not provided
            metadata_url = data.get('metadata_url')

            if not organization_id or not metadata_url:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization ID and metadata URL are required"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify user is admin or owner
                if not await repo.is_admin_or_owner(conn, user_id, UUID(organization_id)):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Unauthorized: Admin or owner role required"
                    ))
                    return

                # Check if org already has SSO configured
                org_row = await repo.get_organization_sso_config(conn, UUID(organization_id))

                if not org_row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Organization not found"
                    ))
                    return

                # If no domain provided, use org slug as a placeholder domain
                # Supabase API requires a domain, but we use provider ID for login so this is just for the API
                effective_domain = domain if domain else f"{org_row['slug']}.noclick.app"

                supabase_admin = get_supabase_admin()

                try:
                    if org_row['sso_provider_id']:
                        # Update existing provider
                        provider = await supabase_admin.update_sso_provider(
                            provider_id=org_row['sso_provider_id'],
                            metadata_url=metadata_url,
                            domains=[effective_domain]
                        )
                    else:
                        # Create new SSO provider in Supabase
                        provider = await supabase_admin.create_sso_provider(
                            metadata_url=metadata_url,
                            domains=[effective_domain],
                            attribute_mapping=data.get('attribute_mapping')
                        )

                    # Update organization with SSO details
                    # Store the user-provided domain (may be null) for display, not the placeholder
                    await repo.set_organization_sso(
                        conn, UUID(organization_id),
                        provider_id=provider.id,
                        domain=domain or None,
                        metadata_url=metadata_url,
                    )

                except SupabaseAdminError as e:
                    logger.error(f"Supabase SSO error: {e}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error=f"Failed to configure SSO: {str(e)}"
                    ))
                    return

            # Get service provider info
            sp_entity_id = supabase_admin.get_saml_entity_id()
            sp_acs_url = supabase_admin.get_saml_acs_url()

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'success': True,
                    'sso_provider_id': provider.id,
                    'domain': domain,
                    'sp_entity_id': sp_entity_id,
                    'sp_acs_url': sp_acs_url,
                    'message': 'SSO configured successfully'
                }
            ))

        except Exception as e:
            logger.error(f"Error configuring SSO: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def disable_sso(self, sid: str, data: dict) -> None:
        """Disable SSO for an organization (admin/owner only)"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            if not organization_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization ID is required"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify user is admin or owner
                if not await repo.is_admin_or_owner(conn, user_id, UUID(organization_id)):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Unauthorized: Admin or owner role required"
                    ))
                    return

                # Get SSO provider ID
                org_row = await repo.get_organization_sso_provider_id(
                    conn, UUID(organization_id)
                )

                if not org_row:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Organization not found"
                    ))
                    return

                # Delete SSO provider in Supabase
                if org_row['sso_provider_id']:
                    try:
                        supabase_admin = get_supabase_admin()
                        await supabase_admin.delete_sso_provider(org_row['sso_provider_id'])
                    except SupabaseAdminError as e:
                        logger.warning(f"Failed to delete SSO provider: {e}")

                # Clear SSO config in database
                await repo.clear_organization_sso(conn, UUID(organization_id))

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'success': True,
                    'message': 'SSO disabled successfully'
                }
            ))

        except Exception as e:
            logger.error(f"Error disabling SSO: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def get_sso_info(self, sid: str, data: dict) -> None:
        """Get SSO configuration info for IdP setup (admin/owner only)"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            if not organization_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization ID is required"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify user is admin or owner
                if not await repo.is_admin_or_owner(conn, user_id, UUID(organization_id)):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Unauthorized: Admin or owner role required"
                    ))
                    return

            # Get service provider info
            supabase_admin = get_supabase_admin()

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'sp_entity_id': supabase_admin.get_saml_entity_id(),
                    'sp_acs_url': supabase_admin.get_saml_acs_url(),
                    'sp_metadata_url': supabase_admin.get_saml_metadata_url(),
                }
            ))

        except Exception as e:
            logger.error(f"Error getting SSO info: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def list_my_organizations(self, sid: str, data: dict) -> None:
        """List all organizations the current user belongs to"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Get all non-personal organizations user is a member of.
                # Personal workspace orgs are excluded — the frontend shows
                # "Personal workspace" as a separate option in the OrgSwitcher.
                rows = await repo.list_my_organizations(conn, user_id)

            organizations = []
            for row in rows:
                organizations.append({
                    'id': str(row['id']),
                    'name': row['name'],
                    'slug': row['slug'],
                    'icon_url': row['icon_url'],
                    'subscription_tier': row['subscription_tier'],
                    'role': row['role'],
                    'is_primary': row['is_primary'] or False,
                })

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={'organizations': organizations}
            ))

        except Exception as e:
            logger.error(f"Error listing user organizations: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def switch_organization(self, sid: str, data: dict) -> None:
        """Switch user's primary organization context"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            # Empty string or None means switch to personal workspace

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                if organization_id:
                    # Verify membership BEFORE touching primary flags — a
                    # non-member request must not clear the user's context.
                    membership = await repo.existing_membership_id(
                        conn, UUID(organization_id), user_id
                    )

                    if not membership:
                        await send_event(self.sio, sid, ResponseEvent(
                            request_id=request_id,
                            data={},
                            error="You are not a member of this organization"
                        ))
                        return

                # All-or-nothing: the user must never be left with no primary
                # context between the clear and the set.
                async with conn.transaction():
                    await repo.clear_all_primary_for_user(conn, user_id)
                    if organization_id:
                        await repo.set_primary(conn, UUID(user_id), UUID(organization_id))
                    else:
                        # Switch to personal workspace — set personal workspace org as primary
                        await repo.set_personal_workspace_primary(conn, UUID(user_id))

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'success': True,
                    'message': 'Organization switched successfully'
                }
            ))

        except Exception as e:
            logger.error(f"Error switching organization: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def upload_icon(self, sid: str, data: dict) -> None:
        """Upload organization icon image (admin/owner only)"""
        request_id = data.get('request_id')
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            organization_id = data.get('organization_id')
            image_data = data.get('image_data')  # Base64 encoded image
            content_type = data.get('content_type', 'image/png')

            if not organization_id or not image_data:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Organization ID and image data are required"
                ))
                return

            # Validate content type
            allowed_types = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']
            if content_type not in allowed_types:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error=f"Invalid content type. Allowed: {', '.join(allowed_types)}"
                ))
                return

            # Get Supabase configuration at runtime (after .env is loaded)
            supabase_url = os.getenv('SUPABASE_URL', '').rstrip('/')
            supabase_secret_key = os.getenv('SUPABASE_SECRET_KEY', '')

            # Validate Supabase configuration
            if not supabase_url or not supabase_secret_key:
                logger.error(f"SUPABASE_URL or SUPABASE_SECRET_KEY not configured. URL present: {bool(supabase_url)}, Key present: {bool(supabase_secret_key)}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Storage service not configured"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            async with pool.acquire() as conn:
                # Verify user is admin or owner
                if not await repo.is_admin_or_owner(conn, user_id, UUID(organization_id)):
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Unauthorized: Admin or owner role required"
                    ))
                    return

                # Get current icon URL to delete later
                current_icon_url = await repo.get_organization_icon(conn, UUID(organization_id))
            # conn released — the storage upload below is external HTTP and
            # must not hold a pinned pool connection.

            # Decode base64 image
            try:
                image_bytes = base64.b64decode(image_data)
            except Exception:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Invalid image data encoding"
                ))
                return

            # Check file size (max 2MB)
            if len(image_bytes) > 2 * 1024 * 1024:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Image too large. Maximum size is 2MB"
                ))
                return

            # Generate unique filename
            ext = content_type.split('/')[-1]
            filename = f"{organization_id}/{uuid4()}.{ext}"

            # Upload to Supabase Storage
            storage_url = f"{supabase_url}/storage/v1/object/{ORG_ICONS_BUCKET}/{filename}"

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    storage_url,
                    content=image_bytes,
                    headers={
                        'apikey': supabase_secret_key,
                        'Content-Type': content_type,
                        'x-upsert': 'true',
                    }
                )

                if response.status_code not in (200, 201):
                    logger.error(f"Storage upload failed: {response.status_code} - {response.text}")
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request_id,
                        data={},
                        error="Failed to upload image to storage"
                    ))
                    return

                # Delete old icon if it exists (after successful upload of new one)
                if current_icon_url:
                    try:
                        # Extract the file path from the URL
                        # URL format: {supabase_url}/storage/v1/object/public/{bucket}/{path}
                        public_prefix = f"/storage/v1/object/public/{ORG_ICONS_BUCKET}/"
                        if public_prefix in current_icon_url:
                            old_path = current_icon_url.split(public_prefix)[-1]
                            delete_url = f"{supabase_url}/storage/v1/object/{ORG_ICONS_BUCKET}/{old_path}"
                            delete_response = await client.delete(
                                delete_url,
                                headers={
                                    'apikey': supabase_secret_key,
                                }
                            )
                            if delete_response.status_code not in (200, 204, 404):
                                # Log but don't fail - the new icon was uploaded successfully
                                logger.warning(f"Failed to delete old icon: {delete_response.status_code} - {delete_response.text}")
                    except Exception as e:
                        # Log but don't fail - the new icon was uploaded successfully
                        logger.warning(f"Error deleting old icon: {e}")

            # Construct public URL
            icon_url = f"{supabase_url}/storage/v1/object/public/{ORG_ICONS_BUCKET}/{filename}"

            # Update organization with icon URL
            async with pool.acquire() as conn:
                await repo.set_organization_icon(conn, UUID(organization_id), icon_url)

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'success': True,
                    'icon_url': icon_url,
                    'message': 'Icon uploaded successfully'
                }
            ))

        except Exception as e:
            logger.error(f"Error uploading icon: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))

    async def check_slug(self, sid: str, data: dict) -> None:
        """Check if a slug is available for organization creation"""
        request_id = data.get('request_id')
        try:
            slug = data.get('slug', '').strip().lower()

            # Validate slug format
            is_valid, error_msg = self._validate_slug(slug)
            if not is_valid:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={
                        'available': False,
                        'slug': slug,
                        'error': error_msg
                    }
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request_id,
                    data={},
                    error="Database connection not available"
                ))
                return

            repo = OrgRepo(pool)
            available = await repo.slug_available(slug)

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={
                    'available': available,
                    'slug': slug
                }
            ))

        except Exception as e:
            logger.error(f"Error checking slug: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request_id,
                data={},
                error=str(e)
            ))
