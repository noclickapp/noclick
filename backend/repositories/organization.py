"""OrgRepo — SQL for organizations, members, invites, and folders.

Owns the SQL for the organization + workflow_folders domains that two large
handlers (``organization_handler.py`` — 50 SQL matches, ``folder_handler.py`` —
28 matches) were previously copy-pasting. Folders are always org-scoped (either
by ``organization_id`` for org workspaces or by ``owner_id + organization_id
IS NULL`` for personal), so the folder SQL sits here alongside membership and
the "current primary org" resolution both handlers use.

Methods take an already-acquired ``conn`` as the first argument so the calling
handler retains control over the pool acquire and transaction boundaries. Two
convenience methods (``slug_available``, ``get_organization_id_by_slug``) also
expose a pool-based variant since they're one-shot standalone reads.

Static column-name interpolation appears in three places: the org-update field
list, the folder-update field list, and the org "list mine" ORDER BY (all
hardcoded — never derived from user input). The update methods enforce the
allowlist explicitly as defense-in-depth in case a new call site wires an
untrusted dict.

The SQL text is preserved verbatim from the two source handlers so behavior
(and existing test SQL-substring assertions) stay identical.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
from uuid import UUID


# ── Column allowlists for dynamic UPDATE statements ─────────────────────────
_ORG_UPDATE_COLUMNS = frozenset({"name", "settings"})
_FOLDER_UPDATE_COLUMNS = frozenset({"name", "description", "parent_folder_id"})


# ── Canonical security-boundary SQL — other repos import and execute these ──
IS_ORG_MEMBER_SQL = (
    "SELECT 1 FROM organization_members "
    "WHERE organization_id = $1 AND user_id = $2"
)

PRIMARY_ORG_SQL = (
    "SELECT organization_id FROM organization_members "
    "WHERE user_id = $1 AND is_primary = true"
)


class OrgRepo:
    """SQL for organizations, members, invites, and workflow_folders.

    Constructor takes the pool proxy; most methods take an outer-acquired
    ``conn`` so the handler owns transaction boundaries. The few pool-only
    methods (``slug_available``, standalone reads) acquire internally.
    """

    def __init__(self, pool):
        self._pool = pool

    # ══════════════════════════════════════════════════════════════════════
    # Membership / role
    # ══════════════════════════════════════════════════════════════════════

    async def get_membership(
        self, conn, user_id: str, organization_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Return the user's membership row for an org (id, role, joined_via,
        created_at) or None if not a member."""
        row = await conn.fetchrow("""
            SELECT id, role, joined_via, created_at
            FROM organization_members
            WHERE organization_id = $1 AND user_id = $2
        """, organization_id, UUID(user_id))
        return dict(row) if row else None

    async def is_admin_or_owner(
        self, conn, user_id: str, organization_id: UUID
    ) -> bool:
        """True if the user is `owner` or `admin` of the org."""
        membership = await self.get_membership(conn, user_id, organization_id)
        return membership is not None and membership["role"] in ("owner", "admin")

    async def is_member(
        self, conn, user_id: str, organization_id: str
    ) -> bool:
        """Lightweight membership check (used by usage dashboard's org gate)."""
        row = await conn.fetchval(IS_ORG_MEMBER_SQL, organization_id, user_id)
        return row is not None

    async def is_member_by_email(
        self, conn, organization_id: UUID, email: str
    ) -> bool:
        """Case-insensitive email membership check (used before invite create)."""
        existing = await conn.fetchval("""
            SELECT om.id FROM organization_members om
            JOIN auth.users u ON u.id = om.user_id
            WHERE om.organization_id = $1 AND LOWER(u.email) = LOWER($2)
        """, organization_id, email)
        return existing is not None

    async def existing_membership_id(
        self, conn, organization_id, user_id: str
    ):
        """Return the membership row id if the user is already a member, else
        None. Used by ``accept_invite`` and ``switch_organization`` where a bool
        answer isn't enough — the caller needs the id for onward flow. The
        organization_id is typed loosely because callers pass either UUID or
        raw str from different code paths."""
        return await conn.fetchval("""
            SELECT id FROM organization_members
            WHERE organization_id = $1 AND user_id = $2
        """, organization_id, UUID(user_id) if isinstance(user_id, str) else user_id)

    # ══════════════════════════════════════════════════════════════════════
    # Personal workspace / primary context
    # ══════════════════════════════════════════════════════════════════════

    async def get_primary_org_id(self, conn, user_id: str) -> Optional[str]:
        """Return the user's currently-primary organization_id (as str), or
        None if they have no primary set. Matches ``folder_handler``'s
        ``get_user_org_context`` — org context iff ``is_primary = true`` on a
        membership row."""
        row = await conn.fetchrow(PRIMARY_ORG_SQL, user_id)
        return str(row["organization_id"]) if row else None

    async def get_personal_workspace_org_id(self, conn, user_id) -> Optional[str]:
        """The user's personal-workspace org (``organizations.is_personal_workspace
        = true``), or None for legacy accounts predating personal-workspace orgs
        that keep their workflows at ``organization_id IS NULL``. This — NOT
        ``organization_id IS NULL`` — is where a normal user's "personal" workflows
        actually live, so it's the correct target for the browser's '' scope.
        Resolved directly (not via is_primary) so switching away from a member org
        can't race it onto the wrong context."""
        org = await conn.fetchval("""
            SELECT om.organization_id
            FROM organization_members om
            JOIN organizations o ON o.id = om.organization_id
            WHERE om.user_id = $1 AND o.is_personal_workspace = true
            LIMIT 1
        """, user_id)
        return str(org) if org else None

    async def resolve_scope_org_id(
        self, conn, user_id: str, scope_org_id: Optional[str]
    ) -> Optional[str]:
        """Resolve the org context for a browser data request (workflow:list /
        workflow_folder:get_tree). The browser passes its scope EXPLICITLY so the
        response matches the scope the request was issued under — immune to the
        ``is_primary`` switch race (the active context is mutable server-side
        session state that lags the client's optimistic org switch, so reading it
        served the previous org's data into the new scope's cache).

        Encoding of ``scope_org_id``:
          - ``None``  → not specified: use the active (is_primary) context
                        (non-browser callers, e.g. MCP, and pre-upgrade clients).
          - ``""``    → personal workspace: the user's PERSONAL-WORKSPACE ORG
                        (where a normal user's workflows live), or None (legacy
                        org_id-IS-NULL accounts). NOT literally ``org NULL`` — most
                        users' personal workflows sit under their personal-workspace
                        org, so forcing NULL hid them (they're only shown via the
                        org path, exactly as the pre-scope is_primary code did).
          - ``"<uuid>"`` → that org IFF the user is a member; otherwise the scope
                        is stale/forged and we resolve to the active context.

        Membership is required to honor an org scope, so a stale or forged scope
        can never read another org's workflows. But a non-member scope must NOT
        raise: the client persists ``org_context`` in IndexedDB, so a user removed
        from an org (or whose org was deleted) legitimately requests a scope they
        no longer belong to on the next load, before OrgSwitcher re-syncs. Erroring
        there blanked the whole browser; instead we fall back to the active context
        (their personal / current-primary data) — safe, and what pre-scope clients
        already got.
        """
        if scope_org_id is None:
            return await self.get_primary_org_id(conn, user_id)
        if scope_org_id == "":
            return await self.get_personal_workspace_org_id(conn, user_id)
        if await self.is_member(conn, user_id, scope_org_id):
            return scope_org_id
        # Stale/forged scope → resolve as the active context (never raise, never leak).
        return await self.get_primary_org_id(conn, user_id)

    async def clear_all_primary_for_user(self, conn, user_id) -> None:
        """Clear the ``is_primary`` flag on every membership row for the user.
        Called before setting a new primary."""
        await conn.execute("""
            UPDATE organization_members SET is_primary = false WHERE user_id = $1
        """, UUID(user_id) if isinstance(user_id, str) else user_id)

    async def set_primary(self, conn, user_id, organization_id) -> None:
        """Set is_primary=true for a specific membership. Caller must have
        already cleared other primaries and verified membership."""
        await conn.execute("""
            UPDATE organization_members
            SET is_primary = true
            WHERE organization_id = $1 AND user_id = $2
        """, organization_id, user_id)

    async def set_personal_workspace_primary(self, conn, user_id) -> None:
        """Restore the personal workspace org (marked
        ``organizations.is_personal_workspace = true``) as the user's primary
        context. Used when switching away from a member org."""
        await conn.execute("""
            UPDATE organization_members om
            SET is_primary = true
            FROM organizations o
            WHERE o.id = om.organization_id
                AND om.user_id = $1
                AND o.is_personal_workspace = true
        """, user_id)

    async def restore_personal_primary_if_no_primary(
        self, conn, user_id
    ) -> None:
        """Conditional: only set the personal workspace as primary if the user
        has NO current primary. Called after removing a user from an org, so
        they land back in their personal context if that removal cleared their
        only primary."""
        await conn.execute("""
            UPDATE organization_members om
            SET is_primary = true
            FROM organizations o
            WHERE o.id = om.organization_id
                AND om.user_id = $1
                AND o.is_personal_workspace = true
                AND NOT EXISTS (
                    SELECT 1 FROM organization_members
                    WHERE user_id = $1 AND is_primary = true
                )
        """, user_id)

    # ══════════════════════════════════════════════════════════════════════
    # Slug
    # ══════════════════════════════════════════════════════════════════════

    async def slug_taken(self, conn, slug: str) -> bool:
        """True if the slug is already used by any organization."""
        existing = await conn.fetchval(
            "SELECT id FROM organizations WHERE slug = $1", slug
        )
        return existing is not None

    async def slug_available(self, slug: str) -> bool:
        """Pool-owning variant used by the ``organization:check_slug`` endpoint
        which has no other DB work in its handler."""
        async with self._pool.acquire() as conn:
            return not await self.slug_taken(conn, slug)

    async def find_unique_slug(
        self, conn, base_slug: str
    ) -> str:
        """Suffix-search a unique slug starting from ``base_slug``, then
        ``base_slug-1``, ``base_slug-2``, ... Mirrors the loop in
        ``create_organization`` verbatim so a probe-per-collision test stays
        deterministic."""
        slug = base_slug
        counter = 1
        while True:
            if not await self.slug_taken(conn, slug):
                return slug
            slug = f"{base_slug}-{counter}"
            counter += 1

    # ══════════════════════════════════════════════════════════════════════
    # Organization CRUD
    # ══════════════════════════════════════════════════════════════════════

    async def insert_organization(
        self, conn, name: str, slug: str, settings: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Insert an organization row and return the newly-created columns the
        handler needs for its response. None if insert failed (impossible in
        practice — the INSERT would raise instead)."""
        row = await conn.fetchrow("""
            INSERT INTO organizations (name, slug, settings)
            VALUES ($1, $2, $3)
            RETURNING id, name, slug, subscription_tier, sso_enabled,
                      sso_domain, created_at, updated_at
        """, name, slug, settings)
        return dict(row) if row else None

    async def get_organization(
        self, conn, organization_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Full org row for the ``organization:get`` endpoint."""
        row = await conn.fetchrow("""
            SELECT id, name, slug, subscription_tier, sso_enabled, sso_domain,
                   sso_metadata_url, settings, icon_url, created_at, updated_at
            FROM organizations
            WHERE id = $1
        """, organization_id)
        return dict(row) if row else None

    async def count_members(self, conn, organization_id: UUID) -> int:
        """Just the member count. Combined with ``get_organization`` for the
        get-org response."""
        return await conn.fetchval("""
            SELECT COUNT(*) FROM organization_members WHERE organization_id = $1
        """, organization_id)

    async def update_organization(
        self, conn, organization_id: UUID, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Dynamic UPDATE against ``organizations`` restricted to the
        ``_ORG_UPDATE_COLUMNS`` allowlist (``name``, ``settings``). Silent-skip
        unknown keys — the caller has already validated its own dict shape.
        Returns the updated row or None if the id didn't exist / no valid
        updates were provided."""
        cols = [c for c in updates if c in _ORG_UPDATE_COLUMNS]
        if not cols:
            return None
        params: List[Any] = [organization_id]
        set_clauses = []
        for i, col in enumerate(cols, start=2):
            set_clauses.append(f"{col} = ${i}")
            params.append(updates[col])
        set_clauses.append("updated_at = NOW()")
        query = f"""
            UPDATE organizations
            SET {', '.join(set_clauses)}
            WHERE id = $1
            RETURNING id, name, slug, subscription_tier, sso_enabled, sso_domain,
                      settings, created_at, updated_at
        """
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None

    async def get_organization_sso_and_icon(
        self, conn, organization_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Fields needed by ``delete_organization`` to clean up SSO provider
        + storage before dropping the row."""
        row = await conn.fetchrow("""
            SELECT sso_provider_id, icon_url FROM organizations WHERE id = $1
        """, organization_id)
        return dict(row) if row else None

    async def get_organization_sso_config(
        self, conn, organization_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """SSO config + slug for the ``configure_sso`` path (needs slug as a
        fallback domain when the caller didn't supply one)."""
        row = await conn.fetchrow("""
            SELECT sso_provider_id, sso_domain, slug FROM organizations WHERE id = $1
        """, organization_id)
        return dict(row) if row else None

    async def get_organization_sso_provider_id(
        self, conn, organization_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Just the sso_provider_id — used by ``disable_sso``."""
        row = await conn.fetchrow("""
            SELECT sso_provider_id FROM organizations WHERE id = $1
        """, organization_id)
        return dict(row) if row else None

    async def set_organization_sso(
        self,
        conn,
        organization_id: UUID,
        *,
        provider_id: str,
        domain: Optional[str],
        metadata_url: str,
    ) -> None:
        """Persist SSO details after a successful Supabase provider create/update."""
        await conn.execute("""
            UPDATE organizations
            SET sso_provider_id = $1,
                sso_domain = $2,
                sso_metadata_url = $3,
                sso_enabled = true,
                updated_at = NOW()
            WHERE id = $4
        """, provider_id, domain, metadata_url, organization_id)

    async def clear_organization_sso(
        self, conn, organization_id: UUID
    ) -> None:
        """Turn off SSO — matches ``disable_sso``."""
        await conn.execute("""
            UPDATE organizations
            SET sso_provider_id = NULL,
                sso_domain = NULL,
                sso_metadata_url = NULL,
                sso_enabled = false,
                updated_at = NOW()
            WHERE id = $1
        """, organization_id)

    async def get_organization_icon(
        self, conn, organization_id: UUID
    ) -> Optional[str]:
        """Return the current icon URL for the org (for old-icon cleanup on upload)."""
        return await conn.fetchval("""
            SELECT icon_url FROM organizations WHERE id = $1
        """, organization_id)

    async def set_organization_icon(
        self, conn, organization_id: UUID, icon_url: str
    ) -> None:
        """Persist a freshly-uploaded icon URL."""
        await conn.execute("""
            UPDATE organizations
            SET icon_url = $1, updated_at = NOW()
            WHERE id = $2
        """, icon_url, organization_id)

    async def delete_organization(
        self, conn, organization_id: UUID
    ) -> str:
        """DELETE FROM organizations. Returns the asyncpg command tag (e.g.
        ``"DELETE 1"``) so the caller can distinguish not-found vs deleted."""
        return await conn.execute("""
            DELETE FROM organizations WHERE id = $1
        """, organization_id)

    async def get_organization_name_and_icon(
        self, conn, organization_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Name + icon URL for the invite-email body."""
        row = await conn.fetchrow("""
            SELECT name, icon_url FROM organizations WHERE id = $1
        """, organization_id)
        return dict(row) if row else None

    async def list_my_organizations(
        self, conn, user_id: str
    ) -> List[Dict[str, Any]]:
        """All non-personal orgs the user is a member of.

        Excludes ``is_personal_workspace = true`` orgs — the frontend
        OrgSwitcher renders "Personal workspace" as its own item.
        """
        rows = await conn.fetch("""
            SELECT
                o.id, o.name, o.slug, o.icon_url, o.subscription_tier,
                om.role,
                om.is_primary
            FROM organization_members om
            JOIN organizations o ON o.id = om.organization_id
            WHERE om.user_id = $1 AND o.is_personal_workspace = false
            ORDER BY om.is_primary DESC, om.created_at ASC
        """, UUID(user_id))
        return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════════════════════════
    # Member limits + billing
    # ══════════════════════════════════════════════════════════════════════

    async def get_member_limit_stats(
        self, conn, organization_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Row for ``_check_member_limit``: org tier, is_personal_workspace,
        current member count, pending-invite count. None if the org doesn't
        exist."""
        row = await conn.fetchrow("""
            SELECT o.subscription_tier, o.is_personal_workspace,
                   (SELECT COUNT(*) FROM organization_members WHERE organization_id = o.id) as member_count,
                   (SELECT COUNT(*) FROM organization_invites
                    WHERE organization_id = o.id
                    AND accepted_at IS NULL
                    AND expires_at > NOW()) as pending_invite_count
            FROM organizations o
            WHERE o.id = $1
        """, organization_id)
        return dict(row) if row else None

    async def get_personal_workspace_owner_tier(
        self, conn, organization_id: UUID
    ) -> Optional[str]:
        """For a personal-workspace org, return the owner's ``user_billing``
        subscription_tier (which is authoritative for the personal case; the
        org's own tier column is not maintained for personal workspaces)."""
        row = await conn.fetchrow("""
            SELECT ub.subscription_tier
            FROM organization_members om
            JOIN user_billing ub ON ub.id = om.user_id
            WHERE om.organization_id = $1 AND om.role = 'owner'
            LIMIT 1
        """, organization_id)
        return row["subscription_tier"] if row else None

    async def set_user_billing_org(
        self, conn, user_id, organization_id
    ) -> None:
        """Point the user's billing row at an org (for org-primary context)."""
        await conn.execute("""
            UPDATE user_billing SET organization_id = $1 WHERE id = $2
        """, organization_id, user_id)

    async def clear_user_billing_org(
        self, conn, user_id, organization_id
    ) -> None:
        """Clear the org reference on the user's billing row IF it currently
        points at ``organization_id`` (safe no-op otherwise)."""
        await conn.execute("""
            UPDATE user_billing SET organization_id = NULL
            WHERE id = $1 AND organization_id = $2
        """, user_id, organization_id)

    # ══════════════════════════════════════════════════════════════════════
    # Members
    # ══════════════════════════════════════════════════════════════════════

    async def list_members(
        self, conn, organization_id: UUID
    ) -> List[Dict[str, Any]]:
        """Members with joined user data (email + raw_user_meta_data) for
        display. Handler formats the display-name from user meta."""
        rows = await conn.fetch("""
            SELECT
                om.id, om.user_id, om.role, om.joined_via, om.created_at,
                u.email, u.raw_user_meta_data
            FROM organization_members om
            JOIN auth.users u ON u.id = om.user_id
            WHERE om.organization_id = $1
            ORDER BY om.created_at ASC
        """, organization_id)
        return [dict(r) for r in rows]

    async def insert_member(
        self,
        conn,
        organization_id,
        user_id,
        role: str,
        joined_via: str,
        *,
        is_primary: bool = True,
    ) -> None:
        """Add a member. Defaults ``is_primary=True`` because both call sites
        (create_organization, accept_invite) simultaneously switch the user's
        primary context to the newly-joined org."""
        if is_primary:
            await conn.execute("""
                INSERT INTO organization_members (organization_id, user_id, role, joined_via, is_primary)
                VALUES ($1, $2, $3, $4, true)
            """, organization_id, user_id, role, joined_via)
        else:
            await conn.execute("""
                INSERT INTO organization_members (organization_id, user_id, role, joined_via, is_primary)
                VALUES ($1, $2, $3, $4, false)
            """, organization_id, user_id, role, joined_via)

    async def delete_member(
        self, conn, organization_id: UUID, user_id: UUID
    ) -> None:
        """Remove a member row. Caller verifies role rules (can't remove owner)."""
        await conn.execute("""
            DELETE FROM organization_members
            WHERE organization_id = $1 AND user_id = $2
        """, organization_id, user_id)

    async def update_member_role(
        self, conn, organization_id: UUID, user_id: UUID, new_role: str
    ) -> None:
        """Update a member's role. Caller validates the new role value."""
        await conn.execute("""
            UPDATE organization_members
            SET role = $1, updated_at = NOW()
            WHERE organization_id = $2 AND user_id = $3
        """, new_role, organization_id, user_id)

    async def transfer_ownership(
        self,
        conn,
        organization_id: UUID,
        current_owner_id: UUID,
        new_owner_id: UUID,
    ) -> None:
        """Atomic role swap: demote current owner → admin, promote target →
        owner. Single-statement CTE keeps it atomic without an explicit
        transaction (avoids the mid-swap intermediate state where the org has
        two or zero owners)."""
        await conn.execute("""
            WITH demote_owner AS (
                UPDATE organization_members
                SET role = 'admin', updated_at = NOW()
                WHERE organization_id = $1 AND user_id = $2
            )
            UPDATE organization_members
            SET role = 'owner', updated_at = NOW()
            WHERE organization_id = $1 AND user_id = $3
        """, organization_id, current_owner_id, new_owner_id)

    # ══════════════════════════════════════════════════════════════════════
    # Invites
    # ══════════════════════════════════════════════════════════════════════

    async def upsert_invite(
        self,
        conn,
        organization_id: UUID,
        email: str,
        role: str,
        invited_by: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Create/refresh an invite. On conflict (same org+email) it re-issues
        the token and pushes expiry out 7 days — matches the current UI
        contract that repeated invites replace prior ones."""
        row = await conn.fetchrow("""
            INSERT INTO organization_invites (organization_id, email, role, invited_by)
            VALUES ($1, LOWER($2), $3, $4)
            ON CONFLICT (organization_id, email)
            DO UPDATE SET
                role = EXCLUDED.role,
                invited_by = EXCLUDED.invited_by,
                expires_at = NOW() + INTERVAL '7 days',
                token = encode(gen_random_bytes(32), 'hex'),
                accepted_at = NULL
            RETURNING id, email, role, token, expires_at, created_at
        """, organization_id, email, role, invited_by)
        return dict(row) if row else None

    async def get_invite_by_token(
        self, conn, token: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch a valid (not accepted, not expired) invite by token, with the
        joined org's name. Used by ``accept_invite``."""
        row = await conn.fetchrow("""
            SELECT oi.id, oi.organization_id, oi.email, oi.role, o.name as org_name
            FROM organization_invites oi
            JOIN organizations o ON o.id = oi.organization_id
            WHERE oi.token = $1
              AND oi.accepted_at IS NULL
              AND oi.expires_at > NOW()
        """, token)
        return dict(row) if row else None

    async def get_invite_details_by_token(
        self, conn, token: str
    ) -> Optional[Dict[str, Any]]:
        """Detailed invite lookup — org name/icon + inviter email — for the
        pre-accept confirmation screen. Does NOT filter accepted/expired
        (caller checks those to show the right error)."""
        row = await conn.fetchrow("""
            SELECT
                oi.id,
                oi.email,
                oi.role,
                oi.expires_at,
                oi.accepted_at,
                o.id as organization_id,
                o.name as organization_name,
                o.icon_url as organization_icon_url,
                u.email as inviter_email
            FROM organization_invites oi
            JOIN organizations o ON o.id = oi.organization_id
            LEFT JOIN auth.users u ON u.id = oi.invited_by
            WHERE oi.token = $1
        """, token)
        return dict(row) if row else None

    async def list_pending_invites(
        self, conn, organization_id: UUID
    ) -> List[Dict[str, Any]]:
        """Pending, un-expired invites for the members UI."""
        rows = await conn.fetch("""
            SELECT id, email, role, expires_at, created_at
            FROM organization_invites
            WHERE organization_id = $1
              AND accepted_at IS NULL
              AND expires_at > NOW()
            ORDER BY created_at DESC
        """, organization_id)
        return [dict(r) for r in rows]

    async def mark_invite_accepted(
        self, conn, invite_id
    ) -> None:
        """Stamp accepted_at=NOW() on the invite row."""
        await conn.execute("""
            UPDATE organization_invites
            SET accepted_at = NOW()
            WHERE id = $1
        """, invite_id)

    async def delete_invite(
        self, conn, invite_id: UUID, organization_id: UUID
    ) -> str:
        """Delete a specific invite. Returns command tag so the caller can
        tell not-found from deleted."""
        return await conn.execute("""
            DELETE FROM organization_invites
            WHERE id = $1 AND organization_id = $2
        """, invite_id, organization_id)

    # ══════════════════════════════════════════════════════════════════════
    # Folders — permission check
    # ══════════════════════════════════════════════════════════════════════

    async def can_access_folder(
        self, conn, user_id: str, folder_id: str
    ) -> bool:
        """Delegates to the DB's ``can_access_folder(user_id, folder_id)``
        function — owner, direct share, or descendant-of-share access. The
        SQL function is the source of truth (see
        ``tests/test_access_control_folders.py``)."""
        return await conn.fetchval(
            "SELECT can_access_folder($1, $2)", user_id, folder_id
        )

    async def get_folder_organization_row(
        self, conn, folder_id
    ) -> Optional[Dict[str, Any]]:
        """Return the folder's organization_id row, or None if the folder
        doesn't exist. The caller distinguishes "folder missing" (None) from
        "personal folder" (row exists with ``organization_id=None``)."""
        row = await conn.fetchrow("""
            SELECT organization_id FROM workflow_folders WHERE id = $1
        """, folder_id)
        return dict(row) if row else None

    async def get_folder_owner(
        self, conn, folder_id
    ) -> Optional[Dict[str, Any]]:
        """Owner id (for permission checks on rename/delete/move)."""
        row = await conn.fetchrow("""
            SELECT owner_id FROM workflow_folders WHERE id = $1
        """, folder_id)
        return dict(row) if row else None

    async def get_folder_owner_and_parent(
        self, conn, folder_id
    ) -> Optional[Dict[str, Any]]:
        """Owner id + parent id — for delete, so the caller can hoist child
        workflows up one level before dropping the folder."""
        row = await conn.fetchrow("""
            SELECT owner_id, parent_folder_id FROM workflow_folders WHERE id = $1
        """, folder_id)
        return dict(row) if row else None

    # ══════════════════════════════════════════════════════════════════════
    # Folders — CRUD
    # ══════════════════════════════════════════════════════════════════════

    async def insert_folder(
        self,
        conn,
        owner_id: str,
        organization_id: Optional[str],
        name: str,
        description: str,
        parent_folder_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Insert a folder. ``path`` and ``depth`` are auto-populated by the
        DB trigger. Personal folders pass ``organization_id=None``; org
        folders inherit the user's current primary org."""
        row = await conn.fetchrow("""
            INSERT INTO workflow_folders (
                owner_id, organization_id, name, description, parent_folder_id
            )
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, name, description, parent_folder_id, path, depth, created_at, updated_at
        """, owner_id, organization_id, name, description, parent_folder_id)
        return dict(row) if row else None

    async def get_folder_with_workflow_count(
        self, conn, folder_id
    ) -> Optional[Dict[str, Any]]:
        """Single-folder read plus its workflow count — for ``get_folder``."""
        row = await conn.fetchrow("""
            SELECT f.id, f.name, f.description, f.parent_folder_id,
                   f.path, f.depth, f.created_at, f.updated_at, f.owner_id,
                   COUNT(w.id) as workflow_count
            FROM workflow_folders f
            LEFT JOIN workflows w ON w.folder_id = f.id
            WHERE f.id = $1
            GROUP BY f.id, f.name, f.description, f.parent_folder_id,
                     f.path, f.depth, f.created_at, f.updated_at, f.owner_id
        """, folder_id)
        return dict(row) if row else None

    async def update_folder(
        self, conn, folder_id, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Dynamic UPDATE with the ``_FOLDER_UPDATE_COLUMNS`` allowlist
        (``name``, ``description``, ``parent_folder_id``). The DB trigger
        recomputes ``path``/``depth`` on parent change. Returns updated row
        or None on empty updates / missing id."""
        cols = [c for c in updates if c in _FOLDER_UPDATE_COLUMNS]
        if not cols:
            return None
        params: List[Any] = [folder_id]
        set_clauses = []
        for i, col in enumerate(cols, start=2):
            set_clauses.append(f"{col} = ${i}")
            params.append(updates[col])
        query = f"""
            UPDATE workflow_folders
            SET {', '.join(set_clauses)}
            WHERE id = $1
            RETURNING id, name, description, parent_folder_id, path, depth, created_at, updated_at
        """
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None

    async def hoist_workflows_to_parent(
        self, conn, folder_id, new_parent_folder_id
    ) -> None:
        """Reparent every workflow in ``folder_id`` to ``new_parent_folder_id``
        (which may be None = root). Called before DELETE so children survive."""
        await conn.execute("""
            UPDATE workflows
            SET folder_id = $1
            WHERE folder_id = $2
        """, new_parent_folder_id, folder_id)

    async def delete_folder(self, conn, folder_id) -> None:
        """DELETE — cascade handles child folders."""
        await conn.execute("""
            DELETE FROM workflow_folders WHERE id = $1
        """, folder_id)

    # ── Folder listing (org context vs personal + shared) ─────────────────

    _LIST_FOLDERS_ORG_SQL_TEMPLATE = """
        SELECT DISTINCT f.id, f.name, f.description, f.parent_folder_id,
               f.path, f.depth, f.created_at, f.updated_at, f.owner_id,
               owner_info.display_name as owner_display_name,
               COUNT(w.id) as workflow_count
        FROM workflow_folders f
        LEFT JOIN workflows w ON w.folder_id = f.id
        LEFT JOIN LATERAL (
            SELECT COALESCE(
                raw_user_meta_data->>'full_name',
                raw_user_meta_data->>'name',
                split_part(email, '@', 1)
            ) as display_name
            FROM auth.users WHERE id = f.owner_id
        ) owner_info ON true
        WHERE f.organization_id = $1
        {parent_condition}
        GROUP BY f.id, f.name, f.description, f.parent_folder_id,
                 f.path, f.depth, f.created_at, f.updated_at, f.owner_id,
                 owner_info.display_name
        ORDER BY f.name ASC
    """

    _LIST_FOLDERS_PERSONAL_SQL_TEMPLATE = """
        SELECT DISTINCT f.id, f.name, f.description, f.parent_folder_id,
               f.path, f.depth, f.created_at, f.updated_at, f.owner_id,
               owner_info.display_name as owner_display_name,
               COUNT(w.id) as workflow_count
        FROM workflow_folders f
        LEFT JOIN workflows w ON w.folder_id = f.id
        LEFT JOIN LATERAL (
            SELECT COALESCE(
                raw_user_meta_data->>'full_name',
                raw_user_meta_data->>'name',
                split_part(email, '@', 1)
            ) as display_name
            FROM auth.users WHERE id = f.owner_id
        ) owner_info ON true
        WHERE (
            -- Owned personal folders
            (f.owner_id = $1 AND f.organization_id IS NULL)
            -- Directly shared with user
            OR EXISTS (
                SELECT 1 FROM resource_shares rs
                WHERE rs.resource_type = 'workflow_folder'
                AND rs.resource_id = f.id
                AND rs.target_type = 'user'
                AND rs.target_user_id = $1
            )
            -- Descendant of a folder shared with user (ancestor path match)
            OR EXISTS (
                SELECT 1
                FROM workflow_folders ancestor
                JOIN resource_shares rs
                    ON rs.resource_type = 'workflow_folder'
                    AND rs.resource_id = ancestor.id
                    AND rs.target_type = 'user'
                    AND rs.target_user_id = $1
                WHERE f.path LIKE ancestor.path || '%'
                  AND ancestor.id != f.id
            )
        )
          {parent_condition}
        GROUP BY f.id, f.name, f.description, f.parent_folder_id,
                 f.path, f.depth, f.created_at, f.updated_at, f.owner_id,
                 owner_info.display_name
        ORDER BY f.name ASC
    """

    async def list_folders(
        self,
        conn,
        *,
        user_id: str,
        org_id: Optional[str],
        parent_folder_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """List folders in the current context.

        Org context (``org_id`` truthy): ALL folders in the org, since org
        members see everything by design.
        Personal context: owned + directly-shared + descendants of shared
        folders (three EXISTS branches).

        ``parent_folder_id`` narrows to a single sub-tree level; ``None``
        returns root-level items only.
        """
        if org_id:
            if parent_folder_id:
                parent_condition = "AND f.parent_folder_id = $2"
                params = [org_id, parent_folder_id]
            else:
                parent_condition = "AND f.parent_folder_id IS NULL"
                params = [org_id]
            sql = self._LIST_FOLDERS_ORG_SQL_TEMPLATE.format(
                parent_condition=parent_condition
            )
        else:
            if parent_folder_id:
                parent_condition = "AND f.parent_folder_id = $2"
                params = [user_id, parent_folder_id]
            else:
                parent_condition = "AND f.parent_folder_id IS NULL"
                params = [user_id]
            sql = self._LIST_FOLDERS_PERSONAL_SQL_TEMPLATE.format(
                parent_condition=parent_condition
            )
        rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

    _FOLDER_TREE_ORG_SQL = """
        SELECT DISTINCT f.id, f.name, f.description, f.parent_folder_id,
               f.path, f.depth, f.created_at, f.updated_at, f.owner_id,
               COUNT(w.id) as workflow_count
        FROM workflow_folders f
        LEFT JOIN workflows w ON w.folder_id = f.id
        WHERE f.organization_id = $1
        GROUP BY f.id, f.name, f.description, f.parent_folder_id,
                 f.path, f.depth, f.created_at, f.updated_at, f.owner_id
        ORDER BY f.depth ASC, f.name ASC
    """

    _FOLDER_TREE_PERSONAL_SQL = """
        SELECT DISTINCT f.id, f.name, f.description, f.parent_folder_id,
               f.path, f.depth, f.created_at, f.updated_at, f.owner_id,
               COUNT(w.id) as workflow_count
        FROM workflow_folders f
        LEFT JOIN workflows w ON w.folder_id = f.id
        WHERE (
            (f.owner_id = $1 AND f.organization_id IS NULL)
            OR EXISTS (
                SELECT 1 FROM resource_shares rs
                WHERE rs.resource_type = 'workflow_folder'
                AND rs.resource_id = f.id
                AND rs.target_type = 'user'
                AND rs.target_user_id = $1
            )
            OR EXISTS (
                SELECT 1
                FROM workflow_folders ancestor
                JOIN resource_shares rs
                    ON rs.resource_type = 'workflow_folder'
                    AND rs.resource_id = ancestor.id
                    AND rs.target_type = 'user'
                    AND rs.target_user_id = $1
                WHERE f.path LIKE ancestor.path || '%'
                  AND ancestor.id != f.id
            )
        )
        GROUP BY f.id, f.name, f.description, f.parent_folder_id,
                 f.path, f.depth, f.created_at, f.updated_at, f.owner_id
        ORDER BY f.depth ASC, f.name ASC
    """

    async def get_folder_tree_rows(
        self, conn, *, user_id: str, org_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """All folders the user can see in current context, ordered by depth
        then name. Handler assembles into a tree by parent_folder_id."""
        if org_id:
            rows = await conn.fetch(self._FOLDER_TREE_ORG_SQL, org_id)
        else:
            rows = await conn.fetch(self._FOLDER_TREE_PERSONAL_SQL, user_id)
        return [dict(r) for r in rows]

    async def get_folder_path(
        self, conn, folder_id: str
    ) -> List[Dict[str, Any]]:
        """Ancestor chain for a folder (breadcrumb). Uses the materialized
        ``path`` column so this is a single index scan, not recursive CTE."""
        rows = await conn.fetch("""
            WITH target_folder AS (
                SELECT path FROM workflow_folders WHERE id = $1
            )
            SELECT f.id, f.name, f.depth
            FROM workflow_folders f, target_folder t
            WHERE t.path LIKE f.path || '%'
            ORDER BY f.depth ASC
        """, folder_id)
        return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════════════════════════
    # Workflow → folder wiring (used by move-to-folder)
    # ══════════════════════════════════════════════════════════════════════

    async def set_workflow_folder(
        self, conn, workflow_id: str, folder_id: Optional[str]
    ) -> None:
        """Direct workflow relocation — owner path or org-share path (shared
        org folder structure)."""
        await conn.execute("""
            UPDATE workflows
            SET folder_id = $1, updated_at = NOW()
            WHERE id = $2
        """, folder_id, workflow_id)

    async def set_share_target_folder(
        self,
        conn,
        workflow_id: str,
        user_id: str,
        folder_id: Optional[str],
    ) -> None:
        """Personal-share recipient's per-user folder placement. Distinct from
        the workflow's canonical folder — a shared workflow can appear in
        different folders for different recipients."""
        await conn.execute("""
            UPDATE resource_shares
            SET target_folder_id = $1, updated_at = NOW()
            WHERE resource_id = $2
                AND resource_type = 'workflow'
                AND target_type = 'user'
                AND target_user_id = $3
        """, folder_id, workflow_id, user_id)
