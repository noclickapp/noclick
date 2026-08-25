"""SkillRepo — SQL for the ``skills`` domain.

Owns every read/write against ``skills``, ``skill_user_mutes``, and the
``resource_shares``/``organization_members`` joins that gate skill visibility.
Also hosts the "which skills can this user load" queries that used to live in
``wss/handlers/skill_queries.py`` — one place per domain (see
``backend/utils/DB_MIGRATION.md``).

Two consumers today:

  * ``wss/handlers/skill_handler.py`` — CRUD + per-user mute state.
  * The workflow builder's skill picker (via ``accessible_skills`` /
    ``load_bodies``).

Rows are converted to ``dict`` at the repo boundary so ``asyncpg.Record`` never
leaks; ``SkillDescriptor`` / ``LoadedSkill`` are the typed shapes for the P0
picker path.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

from repositories.organization import IS_ORG_MEMBER_SQL, PRIMARY_ORG_SQL

logger = logging.getLogger(__name__)


# ── Typed shapes for the P0 picker ──────────────────────────────────────────


@dataclass
class SkillDescriptor:
    """Lightweight shape used for P0 prompt assembly. No body fields."""
    id: str
    name: str
    description: str
    is_system: bool
    has_text: bool
    has_workflow: bool
    scope: str  # 'system' | 'owned' | 'org' | 'shared'


@dataclass
class LoadedSkill:
    """Full skill payload used after P0 picks IDs."""
    id: str
    name: str
    description: str
    is_system: bool
    body_text: Optional[str]
    body_workflow: Optional[Dict[str, Any]]


def parse_jsonb(value: Any) -> Optional[Dict[str, Any]]:
    """Coerce a JSONB cell to a dict.

    The connection-level codec (``utils.database_pool``) decodes JSONB to
    Python objects automatically, so the typical case is that ``value`` is
    already a dict. Rows written before the dict-encoding fix may be
    double-encoded (a JSON string wrapped in a JSON string) — peel up to 3
    layers before giving up.
    """
    if value is None:
        return None
    for _ in range(3):
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            if not value:
                return None
            try:
                value = json.loads(value)
                continue
            except json.JSONDecodeError:
                return None
        break
    return value if isinstance(value, dict) else None


# ── Repo ────────────────────────────────────────────────────────────────────


# Columns callers are allowed to patch on the skills row. Interpolated into
# SQL (asyncpg doesn't parameterize column names), so we gate against a fixed
# allowlist even though today's callers pass hardcoded names — defense in depth
# for the same reason UsageRepo gates ``date_trunc``.
_METADATA_UPDATE_COLUMNS: frozenset = frozenset({
    "name", "description", "body_text", "enabled",
})
_WORKFLOW_UPDATE_COLUMNS: frozenset = frozenset({
    "body_workflow", "display_metadata",
})


class SkillRepo:
    """SQL for the ``skills`` domain — see module docstring.

    Constructor takes a pool proxy from ``DatabasePoolMixin.get_pool()`` or
    the native asyncpg pool. Every method acquires a real pinned connection
    for the duration of its work; multi-statement writes wrap the work in a
    real transaction so BEGIN/COMMIT/ROLLBACK fire (see DB_MIGRATION.md).
    """

    def __init__(self, pool):
        self._pool = pool

    # ── User-scoping helpers ────────────────────────────────────────────

    async def get_user_org_context(self, user_id: str) -> Optional[str]:
        """The user's active org id (is_primary=true), or None for personal."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(PRIMARY_ORG_SQL, user_id)
        return str(row["organization_id"]) if row else None

    async def is_org_member(self, user_id: str, org_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchval(IS_ORG_MEMBER_SQL, org_id, user_id)
        return row is not None

    async def has_share_access(
        self, user_id: str, skill_id: str, *, edit_only: bool = False
    ) -> bool:
        """Any (view/edit) or edit-only ``resource_shares`` row for this skill."""
        if edit_only:
            sql = """
                SELECT 1 FROM resource_shares rs
                LEFT JOIN organization_members om ON om.organization_id = rs.target_org_id
                WHERE rs.resource_type = 'skill'
                  AND rs.resource_id = $1
                  AND rs.permission = 'edit'
                  AND (
                      (rs.target_type = 'user' AND rs.target_user_id = $2)
                      OR (rs.target_type = 'organization' AND om.user_id = $2)
                  )
                LIMIT 1
            """
        else:
            sql = """
                SELECT 1 FROM resource_shares rs
                LEFT JOIN organization_members om ON om.organization_id = rs.target_org_id
                WHERE rs.resource_type = 'skill'
                  AND rs.resource_id = $1
                  AND (
                      (rs.target_type = 'user' AND rs.target_user_id = $2)
                      OR (rs.target_type = 'organization' AND om.user_id = $2)
                  )
                LIMIT 1
            """
        async with self._pool.acquire() as conn:
            row = await conn.fetchval(sql, skill_id, user_id)
        return bool(row)

    async def muted_ids(self, user_id: str, skill_ids: List[str]) -> Set[str]:
        if not skill_ids:
            return set()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT skill_id FROM skill_user_mutes "
                "WHERE user_id = $1 AND skill_id = ANY($2::uuid[])",
                user_id, skill_ids,
            )
        return {str(r["skill_id"]) for r in rows}

    # ── Load / list ─────────────────────────────────────────────────────

    async def load(self, skill_id: str) -> Optional[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM skills WHERE id = $1", skill_id
            )
        return dict(row) if row else None

    async def list_owned_or_org(self, user_id: str) -> List[Dict[str, Any]]:
        """Skills owned by the user or belonging to an org they're a member of."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.* FROM skills s
                WHERE s.is_system = false
                  AND (
                      s.owner_id = $1
                      OR s.organization_id IN (
                          SELECT organization_id FROM organization_members WHERE user_id = $1
                      )
                  )
                ORDER BY s.updated_at DESC
                """,
                user_id,
            )
        return [dict(r) for r in rows]

    async def list_shared(self, user_id: str) -> List[Dict[str, Any]]:
        """Non-system skills shared with the user via ``resource_shares``."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT s.* FROM skills s
                JOIN resource_shares rs ON rs.resource_type = 'skill' AND rs.resource_id = s.id
                LEFT JOIN organization_members om ON om.organization_id = rs.target_org_id
                WHERE s.is_system = false
                  AND (
                      (rs.target_type = 'user' AND rs.target_user_id = $1)
                      OR (rs.target_type = 'organization' AND om.user_id = $1)
                  )
                ORDER BY s.updated_at DESC
                """,
                user_id,
            )
        return [dict(r) for r in rows]

    async def list_system(self) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM skills WHERE is_system = true ORDER BY updated_at DESC"
            )
        return [dict(r) for r in rows]

    # ── Writes ──────────────────────────────────────────────────────────

    async def create(
        self,
        *,
        owner_id: Optional[str],
        organization_id: Optional[str],
        is_system: bool,
        name: str,
        description: str,
        body_text: Optional[str],
        body_workflow: Optional[Dict[str, Any]],
        display_metadata: Dict[str, Any],
        enabled: bool,
    ) -> Dict[str, Any]:
        """Insert a skill and return the created row.

        ``body_workflow`` and ``display_metadata`` are passed as Python dicts —
        the pool's JSONB codec encodes them directly; ``json.dumps`` + a
        ``::jsonb`` cast would double-encode (the string version would land as
        a JSON string scalar, breaking downstream reads).
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO skills
                    (owner_id, organization_id, is_system, name, description,
                     body_text, body_workflow, display_metadata, enabled)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING *
                """,
                owner_id, organization_id, is_system, name, description,
                body_text, body_workflow, display_metadata, enabled,
            )
        return dict(row)

    async def update_metadata(
        self, skill_id: str, patches: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Partial UPDATE against the metadata columns.

        ``patches`` maps column name → new value; unknown columns raise (see
        the ``_METADATA_UPDATE_COLUMNS`` allowlist). Returns the updated row,
        or None on an empty patch — the handler decides how to surface that
        (usually as "no-op success").
        """
        return await self._patch_columns(skill_id, patches, _METADATA_UPDATE_COLUMNS)

    async def update_workflow(
        self, skill_id: str, patches: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Partial UPDATE against ``body_workflow`` / ``display_metadata``.

        Same contract as ``update_metadata``. Dicts are passed to asyncpg
        directly — see ``create`` for why ``json.dumps`` would double-encode.
        """
        return await self._patch_columns(skill_id, patches, _WORKFLOW_UPDATE_COLUMNS)

    async def _patch_columns(
        self,
        skill_id: str,
        patches: Dict[str, Any],
        allowed: frozenset,
    ) -> Optional[Dict[str, Any]]:
        # Empty patch → nothing to do; caller decides the response shape.
        if not patches:
            return None
        fields: List[str] = []
        params: List[Any] = []
        idx = 1
        for column, value in patches.items():
            if column not in allowed:
                raise ValueError(
                    f"column {column!r} is not in the allowlist for skills UPDATE "
                    f"(allowed: {sorted(allowed)})"
                )
            fields.append(f"{column} = ${idx}")
            params.append(value)
            idx += 1
        fields.append("updated_at = NOW()")
        params.append(skill_id)
        sql = f"UPDATE skills SET {', '.join(fields)} WHERE id = ${idx} RETURNING *"
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(sql, *params)
        return dict(row) if row else None

    async def delete(self, skill_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM skills WHERE id = $1", skill_id)

    async def set_mute(self, skill_id: str, user_id: str, muted: bool) -> None:
        async with self._pool.acquire() as conn:
            if muted:
                await conn.execute(
                    """
                    INSERT INTO skill_user_mutes (skill_id, user_id)
                    VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                    """,
                    skill_id, user_id,
                )
            else:
                await conn.execute(
                    "DELETE FROM skill_user_mutes WHERE skill_id = $1 AND user_id = $2",
                    skill_id, user_id,
                )

    # ── P0 picker path ──────────────────────────────────────────────────

    async def accessible_skills(
        self,
        user_id: str,
        *,
        is_internal: bool,
        include_disabled: bool = False,
        include_muted: bool = False,
    ) -> List[SkillDescriptor]:
        """Return descriptors for every skill this user can load into a turn.

        Same visibility rules as ``list_*`` above, plus:
          * excludes ``enabled = false`` unless ``include_disabled`` is set.
          * excludes muted-by-user rows unless ``include_muted`` is set.

        System skills only appear when ``is_internal`` is True.
        """
        # NOTE: the enabled flag is interpolated (not parameterized) because
        # the query has no other reason to run in "no-enabled-filter" mode; the
        # value is a Python bool converted to a fixed SQL fragment.
        enabled_clause = "" if include_disabled else "AND s.enabled = true"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                WITH user_orgs AS (
                    SELECT organization_id FROM organization_members WHERE user_id = $1
                )
                SELECT
                    s.id,
                    s.name,
                    s.description,
                    s.is_system,
                    s.owner_id,
                    s.organization_id,
                    (s.body_text IS NOT NULL AND length(s.body_text) > 0) AS has_text,
                    (s.body_workflow IS NOT NULL) AS has_workflow,
                    CASE
                        WHEN s.is_system THEN 'system'
                        WHEN s.owner_id = $1 THEN 'owned'
                        WHEN s.organization_id IN (SELECT organization_id FROM user_orgs) THEN 'org'
                        ELSE 'shared'
                    END AS scope
                FROM skills s
                WHERE
                    (
                        ($2::bool AND s.is_system = true)
                        OR (s.owner_id = $1)
                        OR (s.organization_id IN (SELECT organization_id FROM user_orgs))
                        OR EXISTS (
                            SELECT 1 FROM resource_shares rs
                            LEFT JOIN organization_members om ON om.organization_id = rs.target_org_id
                            WHERE rs.resource_type = 'skill'
                              AND rs.resource_id = s.id
                              AND (
                                  (rs.target_type = 'user' AND rs.target_user_id = $1)
                                  OR (rs.target_type = 'organization' AND om.user_id = $1)
                              )
                        )
                    )
                    {enabled_clause}
                ORDER BY s.is_system DESC, s.updated_at DESC
                """,
                user_id, is_internal,
            )

            if include_muted:
                muted: Set[str] = set()
            else:
                muted_rows = await conn.fetch(
                    "SELECT skill_id FROM skill_user_mutes WHERE user_id = $1",
                    user_id,
                )
                muted = {str(r["skill_id"]) for r in muted_rows}

        out: List[SkillDescriptor] = []
        for row in rows:
            skill_id = str(row["id"])
            if skill_id in muted:
                continue
            out.append(SkillDescriptor(
                id=skill_id,
                name=row["name"],
                description=row["description"] or "",
                is_system=bool(row["is_system"]),
                has_text=bool(row["has_text"]),
                has_workflow=bool(row["has_workflow"]),
                scope=row["scope"],
            ))
        return out

    async def load_bodies(self, skill_ids: List[str]) -> List[LoadedSkill]:
        """Fetch full bodies for skills P0 picked. Order matches input order."""
        if not skill_ids:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, name, description, is_system, body_text, body_workflow
                FROM skills
                WHERE id = ANY($1::uuid[])
                """,
                skill_ids,
            )
        by_id = {str(r["id"]): r for r in rows}
        out: List[LoadedSkill] = []
        for sid in skill_ids:
            row = by_id.get(sid)
            if not row:
                logger.warning(f"[SkillRepo] Skill {sid} not found during body load")
                continue
            out.append(LoadedSkill(
                id=str(row["id"]),
                name=row["name"],
                description=row["description"] or "",
                is_system=bool(row["is_system"]),
                body_text=row["body_text"],
                body_workflow=parse_jsonb(row["body_workflow"]),
            ))
        return out
