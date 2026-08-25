"""ShareRepo — SQL for resource sharing and forking.

Owns every query the ShareHandler used to inline: resource-shares CRUD,
per-resource ownership/name lookups, org membership checks, invite links,
and workflow/database forking.

The handler retains all auth policy composition — this repo returns primitive
facts (rows, booleans, ids) and the handler decides what to do with them. The
one exception is the three high-level "can I do X" methods
(``can_manage_shares``, ``validate_member_share_target``, ``can_access_resource``)
that are inseparable from their SQL: their SQL and their branching are one
piece and splitting them across the boundary would duplicate the same
resource-type table dispatch in both layers. Same pattern as
``UsageRepo.is_org_member`` — SQL + tiny boolean policy together.

Multi-statement writes that must be atomic (invite-link redemption, workflow
fork, database fork) live in single methods that open one acquire and one
``conn.transaction()`` inside. The prior handler couldn't do this — the runtime
DB proxy silently no-op'd ``conn.transaction()`` — so those writes were
individually idempotent instead. With the 2026-07-01 native asyncpg pool, real
BEGIN/COMMIT/ROLLBACK works and we can consolidate.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

from repositories.organization import IS_ORG_MEMBER_SQL, PRIMARY_ORG_SQL


# ─── Dataclass returns ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class ResourceOwnership:
    """Owner + org for any of the 6 shareable resource types."""
    owner_id: Optional[str]
    organization_id: Optional[str]


@dataclass(frozen=True)
class ShareRow:
    """One row of ``resource_shares``. Field names match the columns."""
    id: str
    resource_type: str
    resource_id: str
    target_type: str
    target_user_id: Optional[str]
    target_email: Optional[str]
    target_org_id: Optional[str]
    permission: str
    shared_by: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


@dataclass(frozen=True)
class PendingInvite:
    """A resource_shares row that has target_email but no target_user_id yet."""
    id: str
    resource_type: str
    resource_id: str
    shared_by: str


@dataclass(frozen=True)
class OrgDisplay:
    name: Optional[str]
    icon_url: Optional[str]


@dataclass(frozen=True)
class UserDisplay:
    """Sharer display info from auth.users.raw_user_meta_data."""
    email: Optional[str]
    avatar_url: Optional[str]
    display_name: Optional[str]


@dataclass(frozen=True)
class UserEmailName:
    email: Optional[str]
    name: Optional[str]


@dataclass(frozen=True)
class WorkflowForInvite:
    """Fields needed to gate invite-link mint on a workflow."""
    owner_id: str
    organization_id: Optional[str]
    is_personal_workspace: Optional[bool]


@dataclass(frozen=True)
class InviteLink:
    token: str
    permission: str


@dataclass(frozen=True)
class InviteLinkDetails:
    workflow_id: str
    permission: str
    created_by: str
    owner_id: str
    workflow_name: Optional[str]


@dataclass(frozen=True)
class InviteRedemptionResult:
    """Result of the 3-write invite redemption.

    ``onboarding_row_created`` drives whether the client must refresh its JWT
    to pick up the new ``onboarding_completed`` claim.
    ``first_redemption`` is True iff this was the first time this
    (invite_token, redeemer) pair was recorded — the durable signal used by
    the caller to fire first-touch analytics attribution.
    """
    onboarding_row_created: bool
    first_redemption: bool


@dataclass(frozen=True)
class WorkflowSource:
    id: str
    name: str
    description: Optional[str]
    workflow: Any  # dict from jsonb
    settings: Any  # dict from jsonb


@dataclass(frozen=True)
class DatabaseSource:
    id: str
    title: str
    description: Optional[str]
    virtual_table_name: str
    display_metadata: Any
    schema_definition: Any


@dataclass(frozen=True)
class ColumnDef:
    column_name: str
    data_type: str
    is_nullable: str
    column_default: Optional[str]






@dataclass(frozen=True)
class SharedWithMeRow:
    """Denormalized row from the shared-with-me JOIN query."""
    resource_type: str
    resource_id: str
    resource_name: Optional[str]
    resource_description: Optional[str]
    permission: str
    shared_at: Optional[datetime]
    shared_by_email: Optional[str]
    shared_by_name: Optional[str]
    organization_id: Optional[str]
    organization_name: Optional[str]


# ─── Repository ────────────────────────────────────────────────────────────

class ShareRepo:
    """SQL for resource sharing and forking.

    Constructor takes a pool proxy. Each method acquires a real pinned
    connection for the duration of its work. Multi-write operations use
    ``async with conn.transaction():`` inside a single acquire.
    """

    # Resource-type dispatch — these column-name interpolations are
    # allowlist-guarded on every use. Each entry: table + owner_id column
    # (all use ``owner_id`` and ``organization_id`` today; the map is here
    # so a future divergence has a single place to encode it).
    _RESOURCE_TABLES: Dict[str, str] = {
        "workflow": "workflows",
        "database": "user_tables_metadata",
        "credential": "credentials",
        "saved_output": "workflow_saved_output",
        "workflow_folder": "workflow_folders",
        "skill": "skills",
    }

    # Per-resource-type name column for display lookups.
    _RESOURCE_NAME_COL: Dict[str, str] = {
        "workflow": "name",
        "database": "title",
        "credential": "name",
        "saved_output": "name",
        "workflow_folder": "name",
        "skill": "name",
    }

    # Types eligible for the "shared with me" JOIN aggregate — the join
    # covers these five. ``skill`` intentionally excluded (owner_id nullable
    # for system skills, join semantics don't match).
    _SHARED_WITH_ME_TYPES = frozenset({
        "workflow", "database", "credential", "saved_output", "workflow_folder",
    })

    # user_tables schema names are always the resource UUID. Guarded against
    # injection via strict UUID regex — the id comes from the metadata row
    # (already a UUID) but defense-in-depth keeps DDL string interpolation safe.
    _UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

    def __init__(self, pool):
        self._pool = pool

    # ─── Resource-type dispatch guards ──────────────────────────────────

    @classmethod
    def _resource_table(cls, resource_type: str) -> Optional[str]:
        """Allowlist the resource_type → table name mapping."""
        return cls._RESOURCE_TABLES.get(resource_type)

    @classmethod
    def _assert_uuid(cls, value: str, label: str) -> None:
        if not cls._UUID_RE.fullmatch(value.lower()):
            raise ValueError(f"{label} must be a UUID, got {value!r}")

    # ─── Resource metadata lookups ──────────────────────────────────────

    async def get_resource_ownership(
        self, resource_type: str, resource_id: str
    ) -> Optional[ResourceOwnership]:
        """Return ``(owner_id, organization_id)`` for a shareable resource.

        For ``skill``, filters out system skills (``is_system=true``) — a
        system skill has no user owner and is not shareable. Returns ``None``
        for unknown resource types.
        """
        table = self._resource_table(resource_type)
        if not table:
            return None
        if resource_type == "skill":
            sql = f"SELECT owner_id, organization_id FROM {table} WHERE id = $1 AND is_system = false"
        else:
            sql = f"SELECT owner_id, organization_id FROM {table} WHERE id = $1"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, resource_id)
        if not row:
            return None
        return ResourceOwnership(
            owner_id=str(row["owner_id"]) if row["owner_id"] else None,
            organization_id=str(row["organization_id"]) if row["organization_id"] else None,
        )

    async def get_resource_org_id(self, resource_type: str, resource_id: str) -> Optional[str]:
        table = self._resource_table(resource_type)
        if not table:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT organization_id FROM {table} WHERE id = $1", resource_id
            )
        if row and row["organization_id"]:
            return str(row["organization_id"])
        return None

    async def get_resource_name(self, resource_type: str, resource_id: str) -> Optional[str]:
        table = self._resource_table(resource_type)
        col = self._RESOURCE_NAME_COL.get(resource_type)
        if not table or not col:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {col} FROM {table} WHERE id = $1", resource_id
            )
        return row[col] if row else None

    async def get_saved_output_is_public(self, resource_id: str) -> Optional[bool]:
        """Return the ``is_public`` flag for a saved_output row, or None if
        the row does not exist. Used by the fork access check."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT is_public FROM workflow_saved_output WHERE id = $1",
                resource_id,
            )
        return bool(row["is_public"]) if row else None

    # ─── Auth primitives ────────────────────────────────────────────────

    async def get_org_membership_role(self, organization_id: str, user_id: str) -> Optional[str]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT role FROM organization_members "
                "WHERE organization_id = $1 AND user_id = $2",
                organization_id, user_id,
            )
        return row["role"] if row else None

    async def is_org_member(self, organization_id: str, user_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchval(IS_ORG_MEMBER_SQL, organization_id, user_id)
        return row is not None

    async def find_user_id_by_email(self, email: str) -> Optional[str]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM auth.users WHERE email = $1", email.lower()
            )
        return str(row["id"]) if row else None

    # ─── Composite auth policies (SQL + tiny boolean policy) ────────────

    async def can_manage_shares(
        self, user_id: str, resource_type: str, resource_id: str
    ) -> bool:
        """Owner or org member can manage shares; system skills refuse.

        Kept as one method because the branching is inseparable from the
        underlying dispatch on resource_type — splitting duplicates the
        table lookup in the handler. Same pattern as
        ``UsageRepo.is_org_member``: SQL + tiny policy in one place.
        """
        ownership = await self.get_resource_ownership(resource_type, resource_id)
        if ownership is None:
            return False
        # System skills (owner_id IS NULL) cannot be shared by users.
        if ownership.owner_id is None:
            return False
        if ownership.owner_id == user_id:
            return True
        if ownership.organization_id:
            role = await self.get_org_membership_role(ownership.organization_id, user_id)
            if role is not None:
                return True
        return False

    async def validate_member_share_target(
        self,
        user_id: str,
        resource_type: str,
        resource_id: str,
        target_type: str,
        target_email: Optional[str],
        target_org_id: Optional[str],
    ) -> Tuple[bool, Optional[str]]:
        """Enforce that org members can only share within their organization.

        Returns ``(is_valid, error_message)``. Admins and owners of the org
        have no restrictions. Members are limited to same-org targets. If the
        resource has no org (personal), no restrictions apply.
        """
        ownership = await self.get_resource_ownership(resource_type, resource_id)
        if ownership is None:
            # Unknown resource type — no restrictions (matches prior behavior).
            return (True, None)
        org_id = ownership.organization_id
        owner_id = ownership.owner_id
        if not org_id:
            return (True, None)

        role = await self.get_org_membership_role(org_id, user_id)

        # Not-a-member but the resource owner (edge case) — allow.
        if role is None and owner_id == user_id:
            return (True, None)

        if role in ("owner", "admin"):
            return (True, None)

        if role == "member":
            if target_type == "organization":
                if target_org_id != org_id:
                    return (
                        False,
                        "Organization members can only share resources within their organization",
                    )
            elif target_type == "user":
                if target_email:
                    target_user_id = await self.find_user_id_by_email(target_email)
                    if target_user_id:
                        target_is_member = await self.is_org_member(org_id, target_user_id)
                        if not target_is_member:
                            return (
                                False,
                                "Organization members can only share with other members of their organization",
                            )
                    else:
                        return (
                            False,
                            "Organization members can only share with existing members of their organization",
                        )

        return (True, None)

    async def can_access_resource(
        self, user_id: str, resource_type: str, resource_id: str
    ) -> bool:
        """View-level access: owner, direct share, org-share, public-share.

        For ``saved_output``, also honors the row's ``is_public`` flag.
        Refuses unknown types.
        """
        if resource_type not in ("workflow", "database", "credential", "saved_output"):
            return False
        ownership = await self.get_resource_ownership(resource_type, resource_id)
        if ownership is None or ownership.owner_id is None:
            return False
        if ownership.owner_id == user_id:
            return True

        if resource_type == "saved_output":
            is_public = await self.get_saved_output_is_public(resource_id)
            if is_public:
                return True

        async with self._pool.acquire() as conn:
            # Direct user share
            direct = await conn.fetchrow(
                """
                SELECT 1 FROM resource_shares
                WHERE resource_type = $1 AND resource_id = $2
                  AND target_type = 'user' AND target_user_id = $3::uuid
                """,
                resource_type, resource_id, user_id,
            )
            if direct:
                return True

            # Org share (user is member of target org)
            org_share = await conn.fetchrow(
                """
                SELECT 1 FROM resource_shares rs
                JOIN organization_members om ON om.organization_id = rs.target_org_id
                WHERE rs.resource_type = $1 AND rs.resource_id = $2
                  AND rs.target_type = 'organization'
                  AND om.user_id = $3::uuid
                """,
                resource_type, resource_id, user_id,
            )
            if org_share:
                return True

            # Public share
            public = await conn.fetchrow(
                """
                SELECT 1 FROM resource_shares
                WHERE resource_type = $1 AND resource_id = $2
                  AND target_type = 'public'
                """,
                resource_type, resource_id,
            )
        return public is not None

    # ─── User / org display lookups (used by _build_share_info) ─────────

    async def get_user_email(self, user_id: str) -> Optional[str]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT email FROM auth.users WHERE id = $1", user_id
            )
        return row["email"] if row else None

    async def get_user_email_and_name(self, user_id: str) -> Optional[UserEmailName]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT email, raw_user_meta_data->>'name' as name FROM auth.users WHERE id = $1",
                user_id,
            )
        if not row:
            return None
        return UserEmailName(email=row["email"], name=row["name"])

    async def get_org_display(self, org_id: str) -> Optional[OrgDisplay]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT name, icon_url FROM organizations WHERE id = $1", org_id
            )
        if not row:
            return None
        return OrgDisplay(name=row["name"], icon_url=row["icon_url"])

    async def get_user_display(self, user_id: str) -> Optional[UserDisplay]:
        """Sharer display info: email + avatar_url + display_name from meta."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT email, "
                "       raw_user_meta_data->>'avatar_url' as avatar_url, "
                "       raw_user_meta_data->>'name' as display_name "
                "FROM auth.users WHERE id = $1",
                user_id,
            )
        if not row:
            return None
        return UserDisplay(
            email=row["email"],
            avatar_url=row["avatar_url"],
            display_name=row["display_name"],
        )

    # ─── Share CRUD ─────────────────────────────────────────────────────

    @staticmethod
    def _share_row_from_record(row) -> ShareRow:
        updated_at = row["updated_at"] if "updated_at" in row.keys() else None
        return ShareRow(
            id=str(row["id"]),
            resource_type=row["resource_type"],
            resource_id=str(row["resource_id"]),
            target_type=row["target_type"],
            target_user_id=str(row["target_user_id"]) if row["target_user_id"] else None,
            target_email=row["target_email"],
            target_org_id=str(row["target_org_id"]) if row["target_org_id"] else None,
            permission=row["permission"],
            shared_by=str(row["shared_by"]),
            created_at=row["created_at"],
            updated_at=updated_at,
        )

    async def get_share_by_id(self, share_id: str) -> Optional[ShareRow]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM resource_shares WHERE id = $1", share_id
            )
        return self._share_row_from_record(row) if row else None

    async def list_shares_for_resource(
        self, resource_type: str, resource_id: str
    ) -> List[ShareRow]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM resource_shares "
                "WHERE resource_type = $1 AND resource_id = $2 "
                "ORDER BY created_at DESC",
                resource_type, resource_id,
            )
        return [self._share_row_from_record(r) for r in rows]

    async def list_pending_invites_for_email(self, email: str) -> List[PendingInvite]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, resource_type, resource_id, shared_by
                FROM resource_shares
                WHERE target_email = $1
                  AND target_user_id IS NULL
                  AND target_type = 'user'
                """,
                email,
            )
        return [
            PendingInvite(
                id=str(r["id"]),
                resource_type=r["resource_type"],
                resource_id=str(r["resource_id"]),
                shared_by=str(r["shared_by"]),
            )
            for r in rows
        ]

    async def link_pending_invite_to_user(self, share_id: str, user_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE resource_shares "
                "SET target_user_id = $1, updated_at = NOW() "
                "WHERE id = $2",
                user_id, share_id,
            )

    async def find_user_share_id(
        self, resource_type: str, resource_id: str, target_user_id: str
    ) -> Optional[str]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id FROM resource_shares
                WHERE resource_type = $1 AND resource_id = $2
                  AND target_type = 'user' AND target_user_id = $3
                """,
                resource_type, resource_id, target_user_id,
            )
        return str(row["id"]) if row else None

    async def find_pending_share_id(
        self, resource_type: str, resource_id: str, target_email: str
    ) -> Optional[str]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id FROM resource_shares
                WHERE resource_type = $1 AND resource_id = $2
                  AND target_type = 'user' AND target_email = $3
                """,
                resource_type, resource_id, target_email.lower(),
            )
        return str(row["id"]) if row else None

    async def find_org_share_id(
        self, resource_type: str, resource_id: str, target_org_id: str
    ) -> Optional[str]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id FROM resource_shares
                WHERE resource_type = $1 AND resource_id = $2
                  AND target_type = 'organization' AND target_org_id = $3
                """,
                resource_type, resource_id, target_org_id,
            )
        return str(row["id"]) if row else None

    async def update_share_permission(
        self, share_id: str, permission: str, *, touch_updated_at: bool = True
    ) -> Optional[ShareRow]:
        """UPDATE permission and RETURN the resulting row.

        ``touch_updated_at`` matches an existing behavior quirk: some callers
        (update_share handler) omit updated_at bumps, while the upsert paths
        include them.
        """
        if touch_updated_at:
            sql = (
                "UPDATE resource_shares "
                "SET permission = $1, updated_at = NOW() "
                "WHERE id = $2 RETURNING *"
            )
        else:
            sql = (
                "UPDATE resource_shares SET permission = $1 "
                "WHERE id = $2 RETURNING *"
            )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, permission, share_id)
        return self._share_row_from_record(row) if row else None

    async def insert_user_share(
        self,
        resource_type: str,
        resource_id: str,
        target_user_id: str,
        permission: str,
        shared_by: str,
    ) -> Optional[ShareRow]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO resource_shares (
                    resource_type, resource_id, target_type,
                    target_user_id, permission, shared_by
                )
                VALUES ($1, $2, 'user', $3, $4, $5)
                RETURNING *
                """,
                resource_type, resource_id, target_user_id, permission, shared_by,
            )
        return self._share_row_from_record(row) if row else None

    async def insert_pending_share(
        self,
        resource_type: str,
        resource_id: str,
        target_email: str,
        permission: str,
        shared_by: str,
    ) -> Optional[ShareRow]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO resource_shares (
                    resource_type, resource_id, target_type,
                    target_email, permission, shared_by
                )
                VALUES ($1, $2, 'user', $3, $4, $5)
                RETURNING *
                """,
                resource_type, resource_id, target_email.lower(), permission, shared_by,
            )
        return self._share_row_from_record(row) if row else None

    async def insert_org_share(
        self,
        resource_type: str,
        resource_id: str,
        target_org_id: str,
        permission: str,
        shared_by: str,
    ) -> Optional[ShareRow]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO resource_shares (
                    resource_type, resource_id, target_type,
                    target_org_id, permission, shared_by
                )
                VALUES ($1, $2, 'organization', $3, $4, $5)
                RETURNING *
                """,
                resource_type, resource_id, target_org_id, permission, shared_by,
            )
        return self._share_row_from_record(row) if row else None

    async def upsert_public_share(
        self, resource_type: str, resource_id: str, shared_by: str
    ) -> Optional[ShareRow]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO resource_shares (
                    resource_type, resource_id, target_type, permission, shared_by
                )
                VALUES ($1, $2, 'public', 'view', $3)
                ON CONFLICT (resource_type, resource_id) WHERE target_type = 'public'
                DO UPDATE SET updated_at = NOW()
                RETURNING *
                """,
                resource_type, resource_id, shared_by,
            )
        return self._share_row_from_record(row) if row else None

    async def delete_share(self, share_id: str) -> bool:
        """Return True if a row was deleted."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM resource_shares WHERE id = $1", share_id
            )
        return result != "DELETE 0"

    async def delete_user_share(
        self, resource_type: str, resource_id: str, user_id: str
    ) -> bool:
        """Self-service unshare: delete the caller's own direct user share.

        Returns True if a row was removed. False means no direct user share
        existed (access may have come via org/folder share, which this can't
        remove).
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM resource_shares
                WHERE resource_type = $1 AND resource_id = $2
                  AND target_type = 'user' AND target_user_id = $3
                """,
                resource_type, resource_id, user_id,
            )
        return result != "DELETE 0"

    async def has_public_share(self, resource_type: str, resource_id: str) -> Optional[str]:
        """Return the public share id if one exists for this resource."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id FROM resource_shares
                WHERE resource_type = $1 AND resource_id = $2 AND target_type = 'public'
                """,
                resource_type, resource_id,
            )
        return str(row["id"]) if row else None

    # ─── Shared-with-me JOIN ────────────────────────────────────────────

    async def list_shared_with_me(
        self, user_id: str, resource_type_filter: Optional[str]
    ) -> List[SharedWithMeRow]:
        """Denormalized list of resources shared with a user.

        Includes direct user shares AND org shares where the user is a
        member. Excludes resources the user owns. When
        ``resource_type_filter`` is passed, restricts to that type.
        """
        params: List[Any] = [user_id]
        type_filter = ""
        if resource_type_filter is not None:
            type_filter = "AND rs.resource_type = $2"
            params.append(resource_type_filter)

        sql = f"""
            SELECT DISTINCT
                rs.resource_type,
                rs.resource_id,
                rs.permission,
                rs.created_at as shared_at,
                sharer.email as shared_by_email,
                sharer.raw_user_meta_data->>'name' as shared_by_name,
                CASE
                    WHEN rs.resource_type = 'workflow' THEN w.name
                    WHEN rs.resource_type = 'database' THEN t.title
                    WHEN rs.resource_type = 'credential' THEN c.name
                    WHEN rs.resource_type = 'saved_output' THEN so.name
                    WHEN rs.resource_type = 'workflow_folder' THEN wf.name
                END as resource_name,
                CASE
                    WHEN rs.resource_type = 'workflow' THEN w.description
                    WHEN rs.resource_type = 'database' THEN t.description
                    WHEN rs.resource_type = 'credential' THEN NULL
                    WHEN rs.resource_type = 'saved_output' THEN NULL
                    WHEN rs.resource_type = 'workflow_folder' THEN wf.description
                END as resource_description,
                CASE
                    WHEN rs.resource_type = 'workflow' THEN w.organization_id
                    WHEN rs.resource_type = 'database' THEN t.organization_id
                    WHEN rs.resource_type = 'credential' THEN c.organization_id
                    WHEN rs.resource_type = 'saved_output' THEN so.organization_id
                    WHEN rs.resource_type = 'workflow_folder' THEN wf.organization_id
                END as organization_id,
                o.name as organization_name
            FROM resource_shares rs
            LEFT JOIN auth.users sharer ON sharer.id = rs.shared_by
            LEFT JOIN workflows w ON rs.resource_type = 'workflow' AND rs.resource_id = w.id
            LEFT JOIN user_tables_metadata t ON rs.resource_type = 'database' AND rs.resource_id = t.id
            LEFT JOIN credentials c ON rs.resource_type = 'credential' AND rs.resource_id = c.id
            LEFT JOIN workflow_saved_output so ON rs.resource_type = 'saved_output' AND rs.resource_id = so.id
            LEFT JOIN workflow_folders wf ON rs.resource_type = 'workflow_folder' AND rs.resource_id = wf.id
            LEFT JOIN organizations o ON (
                CASE
                    WHEN rs.resource_type = 'workflow' THEN w.organization_id
                    WHEN rs.resource_type = 'database' THEN t.organization_id
                    WHEN rs.resource_type = 'credential' THEN c.organization_id
                    WHEN rs.resource_type = 'saved_output' THEN so.organization_id
                    WHEN rs.resource_type = 'workflow_folder' THEN wf.organization_id
                END
            ) = o.id
            WHERE (
                (rs.target_type = 'user' AND rs.target_user_id = $1)
                OR
                (rs.target_type = 'organization' AND rs.target_org_id IN (
                    SELECT organization_id FROM organization_members WHERE user_id = $1
                ))
            )
            AND (
                (rs.resource_type = 'workflow' AND w.owner_id != $1)
                OR
                (rs.resource_type = 'database' AND t.owner_id != $1)
                OR
                (rs.resource_type = 'credential' AND c.owner_id != $1)
                OR
                (rs.resource_type = 'saved_output' AND so.owner_id != $1)
                OR
                (rs.resource_type = 'workflow_folder' AND wf.owner_id != $1)
            )
            {type_filter}
            ORDER BY rs.created_at DESC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [
            SharedWithMeRow(
                resource_type=r["resource_type"],
                resource_id=str(r["resource_id"]),
                resource_name=r["resource_name"],
                resource_description=r["resource_description"],
                permission=r["permission"],
                shared_at=r["shared_at"],
                shared_by_email=r["shared_by_email"],
                shared_by_name=r["shared_by_name"],
                organization_id=str(r["organization_id"]) if r["organization_id"] else None,
                organization_name=r["organization_name"],
            )
            for r in rows
        ]

    # ─── Workflow folder → target-in-org validation ─────────────────────

    async def user_in_org(self, organization_id: str, user_id: str) -> bool:
        """Same as ``is_org_member`` but on a specific caller signature."""
        return await self.is_org_member(organization_id, user_id)

    # ─── Invite links ───────────────────────────────────────────────────

    async def get_workflow_for_invite(self, workflow_id: str) -> Optional[WorkflowForInvite]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT w.owner_id, w.organization_id, o.is_personal_workspace
                FROM workflows w
                LEFT JOIN organizations o ON o.id = w.organization_id
                WHERE w.id = $1 AND w.deleted_at IS NULL
                """,
                workflow_id,
            )
        if not row:
            return None
        return WorkflowForInvite(
            owner_id=str(row["owner_id"]),
            organization_id=str(row["organization_id"]) if row["organization_id"] else None,
            is_personal_workspace=row["is_personal_workspace"],
        )

    async def get_active_invite_link(self, workflow_id: str) -> Optional[InviteLink]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT token, permission FROM workflow_invite_links "
                "WHERE workflow_id = $1 AND is_active = true",
                workflow_id,
            )
        if not row:
            return None
        return InviteLink(token=row["token"], permission=row["permission"])

    async def create_invite_link(
        self, workflow_id: str, token: str, created_by: str
    ) -> Optional[InviteLink]:
        """INSERT a new invite link; return None if a concurrent mint won.

        The caller re-reads with ``get_active_invite_link`` when this returns
        None so the winner's token is surfaced (partial unique index enforces
        one active link per workflow).
        """
        async with self._pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO workflow_invite_links (workflow_id, token, permission, created_by)
                    VALUES ($1, $2, 'edit', $3)
                    RETURNING token, permission
                    """,
                    workflow_id, token, created_by,
                )
            except asyncpg.UniqueViolationError:
                return None
        if not row:
            return None
        return InviteLink(token=row["token"], permission=row["permission"])

    async def get_invite_link_details(self, token: str) -> Optional[InviteLinkDetails]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT il.workflow_id, il.permission, il.created_by,
                       w.owner_id, w.name AS workflow_name
                FROM workflow_invite_links il
                JOIN workflows w ON w.id = il.workflow_id AND w.deleted_at IS NULL
                WHERE il.token = $1 AND il.is_active = true
                """,
                token,
            )
        if not row:
            return None
        return InviteLinkDetails(
            workflow_id=str(row["workflow_id"]),
            permission=row["permission"],
            created_by=str(row["created_by"]),
            owner_id=str(row["owner_id"]),
            workflow_name=row["workflow_name"],
        )

    async def redeem_invite(
        self,
        *,
        workflow_id: str,
        user_id: str,
        permission: str,
        owner_id: str,
        invite_token: str,
    ) -> InviteRedemptionResult:
        """3-write invite redemption. Idempotent + atomic.

        With the 2026-07-01 native pool, this now runs inside a real
        transaction — the prior handler couldn't (proxy no-op'd
        ``conn.transaction()``) and relied on per-row idempotency. Real
        atomicity is strictly better: a partial failure can't leave a
        redemption row without its onboarding write.
        """
        onboarding_responses = {
            "how_did_you_hear": "referral",
            "referred_by": owner_id,
            "referred_via_workflow": workflow_id,
            "invite_token": invite_token,
        }
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO resource_shares (
                        resource_type, resource_id, target_type,
                        target_user_id, permission, shared_by
                    )
                    VALUES ('workflow', $1, 'user', $2, $3, $4)
                    ON CONFLICT (resource_type, resource_id, target_user_id)
                        WHERE target_type = 'user' AND target_user_id IS NOT NULL
                    DO UPDATE SET permission = EXCLUDED.permission, updated_at = NOW()
                    """,
                    workflow_id, user_id, permission, owner_id,
                )

                onboarding_row = await conn.fetchrow(
                    """
                    INSERT INTO user_onboarding_responses (user_id, responses, version)
                    VALUES ($1, $2::jsonb, 1)
                    ON CONFLICT (user_id) DO NOTHING
                    RETURNING id
                    """,
                    user_id, onboarding_responses,
                )

                redemption_row = await conn.fetchrow(
                    """
                    INSERT INTO invite_redemptions (invite_token, workflow_id, inviter_id, redeemer_id)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (invite_token, redeemer_id) DO NOTHING
                    RETURNING id
                    """,
                    invite_token, workflow_id, owner_id, user_id,
                )

        return InviteRedemptionResult(
            onboarding_row_created=onboarding_row is not None,
            first_redemption=redemption_row is not None,
        )

    # ─── Fork: workflow ─────────────────────────────────────────────────

    async def get_workflow_source(self, workflow_id: str) -> Optional[WorkflowSource]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, name, description, workflow, settings "
                "FROM workflows WHERE id = $1",
                workflow_id,
            )
        if not row:
            return None
        return WorkflowSource(
            id=str(row["id"]),
            name=row["name"],
            description=row["description"],
            workflow=row["workflow"],
            settings=row["settings"],
        )

    async def insert_forked_workflow(
        self,
        *,
        new_id: str,
        name: str,
        description: Optional[str],
        workflow_data: Any,
        owner_id: str,
        org_id: Optional[str],
        settings: Any,
        source_workflow_id: str,
        forked_by: str,
    ) -> None:
        """Create the workflow and fork edge in one transaction."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO workflows (id, name, description, workflow, owner_id, organization_id, settings)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    new_id, name, description, workflow_data, owner_id, org_id, settings,
                )
                await conn.execute(
                    """
                    INSERT INTO resource_forks (resource_type, source_id, forked_id, forked_by)
                    VALUES ('workflow', $1::uuid, $2::uuid, $3::uuid)
                    """,
                    source_workflow_id, new_id, forked_by,
                )

    # ─── Fork: database ─────────────────────────────────────────────────

    async def get_database_source(self, source_table_id: str) -> Optional[DatabaseSource]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, title, description, virtual_table_name, display_metadata, schema_definition
                FROM user_tables_metadata
                WHERE id = $1
                """,
                source_table_id,
            )
        if not row:
            return None
        return DatabaseSource(
            id=str(row["id"]),
            title=row["title"],
            description=row["description"],
            virtual_table_name=row["virtual_table_name"],
            display_metadata=row["display_metadata"],
            schema_definition=row["schema_definition"],
        )

    async def get_user_table_columns(self, table_id: str) -> List[ColumnDef]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'user_tables' AND table_name = $1
                ORDER BY ordinal_position
                """,
                table_id,
            )
        return [
            ColumnDef(
                column_name=r["column_name"],
                data_type=r["data_type"],
                is_nullable=r["is_nullable"],
                column_default=r["column_default"],
            )
            for r in rows
        ]

    async def insert_forked_database(
        self,
        *,
        new_id: str,
        title: str,
        description: Optional[str],
        virtual_table_name: str,
        owner_id: str,
        org_id: Optional[str],
        display_metadata: Any,
        schema_definition: Any,
        create_table_columns: List[str],
        source_table_id: str,
        forked_by: str,
        copy_data_columns: Optional[List[str]],
    ) -> None:
        """Metadata insert + CREATE TABLE + optional data copy + fork edge, in
        one transaction so a partial fork can't leave orphaned rows.

        DDL is dynamic — new_id and source_table_id become schema-qualified
        table names. Both come from server-generated UUIDs (uuid4() for
        new_id; the source row's id column). We hard-validate the UUID shape
        here as defense-in-depth: an injection into DDL is a much worse
        failure mode than an injection into DML.
        """
        self._assert_uuid(new_id, "new_id")
        self._assert_uuid(source_table_id, "source_table_id")

        create_table_sql = (
            f'CREATE TABLE user_tables."{new_id}" ({", ".join(create_table_columns)})'
        )
        cols_str = None
        copy_sql = None
        if copy_data_columns:
            cols_str = ", ".join(f'"{c}"' for c in copy_data_columns)
            copy_sql = (
                f'INSERT INTO user_tables."{new_id}" ({cols_str}) '
                f'SELECT {cols_str} FROM user_tables."{source_table_id}"'
            )

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO user_tables_metadata (
                        id, title, description, virtual_table_name,
                        owner_id, organization_id, source,
                        display_metadata, schema_definition
                    )
                    VALUES ($1::uuid, $2, $3, $4, $5, $6, 'managed', $7, $8)
                    """,
                    new_id, title, description, virtual_table_name,
                    owner_id, org_id, display_metadata, schema_definition,
                )
                await conn.execute(create_table_sql)
                if copy_sql is not None:
                    await conn.execute(copy_sql)
                await conn.execute(
                    """
                    INSERT INTO resource_forks (resource_type, source_id, forked_id, forked_by)
                    VALUES ('database', $1::uuid, $2::uuid, $3::uuid)
                    """,
                    source_table_id, new_id, forked_by,
                )

    # ─── User org context (for personal-workspace fork target) ──────────

    async def get_user_primary_org(self, user_id: str) -> Optional[str]:
        """The user's primary org for the fork target — executes the
        canonical ``OrgRepo`` primary-org SQL."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(PRIMARY_ORG_SQL, user_id)
        return str(row["organization_id"]) if row else None
