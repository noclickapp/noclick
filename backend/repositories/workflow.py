"""WorkflowRepo — SQL for workflows, executions, checkpoints, node state,
build requests, and workflow-scoped folder ops.

Owns the SQL for the five biggest workflow-domain handlers
(``workflow_handler``, ``workflow_mcp_handler``, ``workflow_execution_handler``,
``workflow_checkpoint_handler``, ``workflow_builder_handler``) that were
previously assembling multi-hundred lines of inline SQL against a handful of
central tables.

Tables in scope: ``workflows``, ``workflow_executions``, ``workflow_checkpoints``,
``workflow_node_state``, and — for
``workflow_builder_handler``'s platform_ops — ``workflow_folders`` (owner-scoped
variants; the org-wide folder-tree queries stay in OrgRepo).

Methods take an already-acquired ``conn`` where callers own the acquire /
transaction. Pool-owning variants are provided for standalone one-shots (e.g.
the background rename in ``_generate_workflow_name_background``, where the
caller has no other DB work in scope).

Static column-name interpolation appears in four spots — the workflow-update
column list, the workflow-list folder-filter branches, the mcp-list branch, and
the mcp workflow-metadata dynamic UPDATE. All three interpolations are
allowlist-guarded (folder filter is a fixed set of string literals; update
columns are validated against ``_WORKFLOW_UPDATE_COLUMNS`` /
``_WORKFLOW_METADATA_COLUMNS``). See DB_MIGRATION.md for the rules.

SQL text is preserved verbatim from the source handlers so behavior (and any
tests asserting on SQL substrings) stays identical.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID


# ── Column allowlists ──────────────────────────────────────────────────────
# The dynamic UPDATE builders emit `col = $N` from a user-supplied dict; the
# column NAMES must come from a fixed allowlist so a malicious caller can't
# inject SQL by naming a bogus column. Each set is the union of what the
# corresponding handler was already writing.
_WORKFLOW_UPDATE_COLUMNS = frozenset({
    "name", "description", "workflow", "permissions",
    "display_metadata", "settings",
})
_WORKFLOW_METADATA_COLUMNS = frozenset({"name", "description"})


def _try_parse_uuid(value: Optional[str]) -> Optional[UUID]:
    """Return the parsed UUID, or None when ``value`` isn't a UUID string.

    Lets the workflow-list search treat a query that IS a workflow id as an
    id lookup — the AI builder and MCP server both pass a bare id to
    ``list_workflows`` when recovering a specific workflow, and a name/desc-only
    ILIKE returns nothing for it (the workflow is usually named "Untitled")."""
    try:
        return UUID(value)  # type: ignore[arg-type]
    except (ValueError, AttributeError, TypeError):
        return None


def get_workflow_owner_sql(include_deleted: bool = False) -> str:
    """Canonical workflow-owner lookup ($1 = workflow_id). By default a
    trashed (soft-deleted) workflow does NOT resolve; ``include_deleted``
    keeps it resolvable for run-as-owner / cleanup paths."""
    sql = "SELECT owner_id FROM workflows WHERE id = $1"
    return sql if include_deleted else sql + " AND deleted_at IS NULL"


class WorkflowRepo:
    """SQL for the workflow domain — CRUD, executions, checkpoints, node
    state, build requests, plus the owner-scoped folder ops that the
    workflow builder's platform_ops uses.

    Constructor takes the pool proxy from ``DatabasePoolMixin.get_pool()``.
    Most methods take an outer-acquired ``conn`` so the caller retains
    control over transaction boundaries; pool-owning variants exist for
    standalone one-shot reads and the background name-rename write.
    """

    def __init__(self, pool):
        self._pool = pool

    # ══════════════════════════════════════════════════════════════════════
    # Workflow — single-row reads
    # ══════════════════════════════════════════════════════════════════════

    async def get_owner_id(
        self, workflow_id, *, include_deleted: bool = False
    ) -> Optional[str]:
        """Owner id for a workflow, or None if it doesn't exist (or is
        trashed, unless ``include_deleted``). THE owner-lookup boundary —
        auth checks and run-as-owner resolution both compose from
        ``get_workflow_owner_sql``."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                get_workflow_owner_sql(include_deleted), workflow_id
            )
        return str(row["owner_id"]) if row and row["owner_id"] else None

    async def get_workflow_full(
        self, conn, workflow_id
    ) -> Optional[Dict[str, Any]]:
        """Full workflow row for the ``workflow:get`` endpoint (all
        user-visible fields except ``owner_id`` / ``organization_id``)."""
        row = await conn.fetchrow("""
            SELECT id, name, description, workflow, permissions, created_at, updated_at, display_metadata, settings, graph_version
            FROM workflows
            WHERE id = $1
        """, workflow_id)
        return dict(row) if row else None

    async def get_workflow_data(
        self, conn, workflow_id
    ) -> Optional[Dict[str, Any]]:
        """Just the ``workflow`` JSONB blob — used by SDK get_node_config and
        state_manager node lookup."""
        row = await conn.fetchrow(
            "SELECT workflow FROM workflows WHERE id = $1",
            workflow_id,
        )
        return dict(row) if row else None

    async def get_workflow_for_mcp_load(
        self, conn, workflow_id
    ) -> Optional[Dict[str, Any]]:
        """Load-only variant used by the MCP handler's ``_load_workflow``."""
        row = await conn.fetchrow(
            "SELECT workflow FROM workflows WHERE id = $1",
            workflow_id,
        )
        return dict(row) if row else None

    async def get_workflow_execution_context(
        self, conn, workflow_id
    ) -> Optional[Dict[str, Any]]:
        """The (workflow, organization_id, settings) trio the execution
        handler's ``_fetch_workflow`` reads to seed a run."""
        row = await conn.fetchrow("""
            SELECT workflow, organization_id, settings FROM workflows
            WHERE id = $1
        """, workflow_id)
        return dict(row) if row else None

    async def get_workflow_org_and_data(
        self, conn, workflow_id
    ) -> Optional[Dict[str, Any]]:
        """Used when the FE provided nodes/edges directly and the executor
        only needs the ``organization_id`` / ``workflow`` / ``settings``
        columns (see ``_handle_execute_impl``)."""
        row = await conn.fetchrow(
            "SELECT organization_id, workflow, settings FROM workflows WHERE id = $1",
            workflow_id,
        )
        return dict(row) if row else None

    async def get_workflow_data_and_settings(
        self, conn, workflow_id
    ) -> Optional[Dict[str, Any]]:
        """(workflow, settings) — used on the resume path."""
        row = await conn.fetchrow(
            "SELECT workflow, settings FROM workflows WHERE id = $1",
            workflow_id,
        )
        return dict(row) if row else None

    async def workflow_exists_for_owner(
        self, conn, workflow_id, user_id
    ) -> bool:
        """True if the workflow exists AND is owned by ``user_id`` (soft-
        deleted rows still count — used before soft-delete + before
        run_node in the builder platform_ops)."""
        return await conn.fetchval("""
            SELECT 1 FROM workflows WHERE id = $1 AND owner_id = $2
        """, workflow_id, user_id) is not None

    async def workflow_in_trash_for_owner(
        self, conn, workflow_id, user_id
    ) -> bool:
        """True if the workflow is soft-deleted AND owned by ``user_id`` —
        used before permanent-delete."""
        return await conn.fetchval("""
            SELECT 1 FROM workflows
            WHERE id = $1 AND owner_id = $2 AND deleted_at IS NOT NULL
        """, workflow_id, user_id) is not None

    async def get_workflow_for_builder_run_node(
        self, conn, workflow_id, user_id
    ) -> Optional[Dict[str, Any]]:
        """Owner-gated workflow-data fetch for the builder platform_ops
        ``run_node`` (which must never dispatch a run against a workflow
        the actor doesn't own)."""
        row = await conn.fetchrow(
            "SELECT workflow FROM workflows WHERE id = $1 AND owner_id = $2",
            workflow_id, user_id,
        )
        return dict(row) if row else None

    # ══════════════════════════════════════════════════════════════════════
    # Workflow — create / update / delete
    # ══════════════════════════════════════════════════════════════════════

    async def create_workflow(
        self,
        conn,
        *,
        owner_id: str,
        organization_id: Optional[str],
        folder_id: Optional[str],
        name: str,
        description: str,
        workflow_data: Dict[str, Any],
        permissions: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """The full workflow-create INSERT used by ``workflow:create``.
        Returns the columns the handler echoes back in ``WorkflowInfo``."""
        row = await conn.fetchrow("""
            INSERT INTO workflows (owner_id, organization_id, folder_id, name, description, workflow, permissions, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
            RETURNING id, name, description, workflow, permissions, created_at, updated_at
        """, owner_id, organization_id, folder_id, name, description, workflow_data, permissions)
        return dict(row) if row else None

    async def create_workflow_mcp(
        self,
        conn,
        *,
        owner_id: str,
        name: str,
        description: str,
        workflow_data: Dict[str, Any],
        permissions: Dict[str, Any],
        folder_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """MCP ``create_workflow`` variant — no org context, returns only
        the id/name/description the MCP response needs."""
        row = await conn.fetchrow("""
            INSERT INTO workflows (owner_id, name, description, workflow, permissions, folder_id, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
            RETURNING id, name, description
        """, owner_id, name, description, workflow_data, permissions, folder_id)
        return dict(row) if row else None

    async def create_workflow_builder(
        self,
        conn,
        *,
        name: str,
        description: str,
        owner_id: UUID,
        organization_id: Optional[UUID],
        workflow_data: Dict[str, Any],
    ) -> Any:
        """Builder platform_ops ``create_workflow`` — returns the new
        workflow id (UUID), matching the caller's ``fetchval`` expectation."""
        return await conn.fetchval(
            """INSERT INTO workflows (name, description, owner_id, organization_id, workflow)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            name, description, owner_id, organization_id, workflow_data,
        )

    async def insert_workflow_org_share(
        self,
        conn,
        *,
        workflow_id,
        organization_id,
        permission: str,
        shared_by,
    ) -> None:
        """Share a newly-created workflow with an org. Callers passing this
        also just created the workflow — the two writes together form the
        "create in org context" transaction. This method's SQL is the same
        one both ``workflow_handler.create_workflow`` and the builder
        platform_ops use; kept here so the pattern lives in one place."""
        await conn.execute("""
            INSERT INTO resource_shares (resource_type, resource_id, target_type, target_org_id, permission, shared_by)
            VALUES ('workflow', $1, 'organization', $2, $3, $4)
        """, workflow_id, organization_id, permission, shared_by)

    async def update_workflow_dynamic(
        self,
        conn,
        workflow_id,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        workflow_data: Optional[Dict[str, Any]] = None,
        permissions: Optional[Dict[str, Any]] = None,
        display_metadata: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
        expected_graph_version: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """The composite update the ``workflow:update`` endpoint runs — a
        dynamic set of column assignments (all optional) plus a CTE that
        captures the previous ``name`` and ``workflow`` blob so the caller
        can compute a delta for Slack notifications without a second read.

        Rules (from the source handler):
          - ``workflow_data`` MUST preserve existing ``variables`` if the
            incoming blob doesn't include them (setup flow writes variables
            via jsonb_set; auto-saves may not).
          - ``settings`` merges into the existing JSONB rather than replacing.
          - Returns None if no updatable fields were supplied.
          - ``expected_graph_version`` (only meaningful with ``workflow_data``)
            adds a CAS guard: the UPDATE matches zero rows if another writer
            bumped ``graph_version`` since this client loaded — the caller
            distinguishes conflict from not-found with a follow-up read.
        """
        updates: List[str] = []
        params: List[Any] = [workflow_id]
        idx = 2

        if name is not None:
            updates.append(f"name = ${idx}")
            params.append(name)
            idx += 1
        if description is not None:
            updates.append(f"description = ${idx}")
            params.append(description)
            idx += 1
        if workflow_data is not None:
            updates.append(
                f"workflow = CASE "
                f"WHEN ${idx}::jsonb ? 'variables' THEN ${idx}::jsonb "
                f"ELSE ${idx}::jsonb || jsonb_build_object('variables', COALESCE(workflow->'variables', '{{}}'::jsonb)) "
                f"END"
            )
            params.append(workflow_data)
            idx += 1
        if permissions is not None:
            updates.append(f"permissions = ${idx}")
            params.append(permissions)
            idx += 1
        if display_metadata is not None:
            updates.append(f"display_metadata = ${idx}")
            params.append(display_metadata)
            idx += 1
        if settings is not None:
            updates.append(f"settings = COALESCE(settings, '{{}}'::jsonb) || ${idx}::jsonb")
            params.append(settings)
            idx += 1

        if not updates:
            return None

        # updated_at semantics are owned by the workflows_touch_updated_at_
        # content_only trigger (bumps on content changes, preserved on
        # display-state-only writes) — this SET is just the legacy default
        # the trigger overrides either way.
        updates.append("updated_at = NOW()")

        where = "id = $1"
        if workflow_data is not None and expected_graph_version is not None:
            where += f" AND graph_version = ${idx}"
            params.append(expected_graph_version)
            idx += 1

        query = f"""
            WITH old AS (
                SELECT name, workflow FROM workflows WHERE id = $1
            )
            UPDATE workflows
            SET {', '.join(updates)}
            WHERE {where}
            RETURNING id, name, description, workflow, permissions, created_at, updated_at, display_metadata, settings, graph_version,
                      (SELECT name FROM old) as old_name,
                      (SELECT workflow FROM old) as old_workflow
        """
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None

    async def update_workflow_metadata(
        self,
        conn,
        workflow_id,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """MCP ``update_workflow_metadata`` — the smaller, dynamic UPDATE
        restricted to ``name`` and ``description``. Returns updated
        (name, description) or None if the id didn't exist / no valid keys."""
        cols = [c for c in updates if c in _WORKFLOW_METADATA_COLUMNS]
        if not cols:
            return None
        set_clauses = []
        params: List[Any] = []
        for i, col in enumerate(cols, start=1):
            set_clauses.append(f"{col} = ${i}")
            params.append(updates[col])
        set_clauses.append("updated_at = NOW()")
        params.append(workflow_id)
        query = f"""
            UPDATE workflows
            SET {', '.join(set_clauses)}
            WHERE id = ${len(cols) + 1}
            RETURNING name, description
        """
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None

    async def rename_workflow_if_owner(
        self,
        workflow_id: str,
        name: str,
        description: str,
        owner_id: str,
        *,
        placeholder_only: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Background rename run by the builder — owner-gated so a
        collaborator can't hijack the generated name. Pool-owning because
        the caller has no other DB work in scope.

        placeholder_only: only land if the current name is still a default
        placeholder — the retry path fires on later builder turns, by which
        point the user may have typed a real name that must win."""
        guard = (
            " AND name IN ('', 'Untitled', 'Untitled Workflow')"
            if placeholder_only else ""
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE workflows
                SET name = $2, description = $3, updated_at = NOW()
                WHERE id = $1 AND owner_id = $4{guard}
                RETURNING id, name, description
                """,
                workflow_id, name, description, owner_id,
            )
        return dict(row) if row else None

    async def replace_workflow_data(
        self, conn, workflow_id, workflow_data: Dict[str, Any]
    ) -> str:
        """Full replace of the ``workflow`` JSONB blob — used by the MCP
        ``_save_workflow`` and by ``restore_checkpoint``. Returns the asyncpg
        command tag so the caller can distinguish ``"UPDATE 0"``."""
        return await conn.execute("""
            UPDATE workflows
            SET workflow = $1, updated_at = NOW()
            WHERE id = $2
        """, workflow_data, workflow_id)

    async def soft_delete_workflow(
        self, conn, workflow_id, user_id
    ) -> None:
        """Move a workflow to trash. Owner-scoped."""
        await conn.execute("""
            UPDATE workflows SET deleted_at = NOW()
            WHERE id = $1 AND owner_id = $2
        """, workflow_id, user_id)

    async def soft_delete_workflow_by_id(
        self, conn, workflow_id
    ) -> None:
        """MCP variant — owner check is done by the caller via
        ``check_resource_access`` (which the MCP handler runs before
        every mutation). No ``owner_id`` predicate."""
        await conn.execute("""
            UPDATE workflows SET deleted_at = NOW()
            WHERE id = $1
        """, workflow_id)

    async def restore_workflow(
        self, conn, workflow_id, user_id
    ) -> str:
        """Restore from trash. Returns the command tag so the caller can
        surface "not in trash" via ``UPDATE 0``."""
        return await conn.execute("""
            UPDATE workflows SET deleted_at = NULL
            WHERE id = $1 AND owner_id = $2 AND deleted_at IS NOT NULL
        """, workflow_id, user_id)

    async def hard_delete_workflow(
        self, conn, workflow_id, user_id
    ) -> bool:
        """Permanent delete after resource cleanup.

        The NOT EXISTS guard is the final CAS against a run starting between
        the handler's stop/wait phase and this delete. Returns whether the row
        was deleted.
        """
        result = await conn.execute("""
            DELETE FROM workflows
            WHERE id = $1 AND owner_id = $2
              AND NOT EXISTS (
                  SELECT 1 FROM workflow_executions e
                  WHERE e.workflow_id = workflows.id
                    AND e.status = 'running'
                    AND e.finished_at IS NULL
              )
        """, workflow_id, user_id)
        return result == "DELETE 1"

    async def list_running_execution_ids(
        self, conn, workflow_id
    ) -> List[str]:
        """Execution ids whose worker may still produce side effects/writes."""
        rows = await conn.fetch("""
            SELECT id
            FROM workflow_executions
            WHERE workflow_id = $1
              AND status = 'running'
              AND finished_at IS NULL
            ORDER BY started_at
        """, workflow_id)
        return [str(row['id']) for row in rows]

    async def list_trash(
        self, conn, user_id
    ) -> List[Dict[str, Any]]:
        """All soft-deleted workflows owned by ``user_id``."""
        rows = await conn.fetch("""
            SELECT id, name, description, deleted_at
            FROM workflows
            WHERE owner_id = $1 AND deleted_at IS NOT NULL
            ORDER BY deleted_at DESC
        """, user_id)
        return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════════════════════════
    # Workflow — list (org / personal contexts, folder filters, shares)
    # ══════════════════════════════════════════════════════════════════════

    # These three "folder filter" clause fragments are the ONLY interpolated
    # variants — a fixed lookup rather than user-derived strings.
    _FOLDER_FILTERS_ORG: Dict[str, str] = {
        "byid": "AND w.folder_id = $3",
        "root": "AND w.folder_id IS NULL",
        "any":  "",
    }
    _FOLDER_FILTERS_PERSONAL_OWN: Dict[str, str] = {
        "byid": "AND w.folder_id = $2",
        "root": "AND w.folder_id IS NULL",
        "any":  "",
    }
    _FOLDER_FILTERS_PERSONAL_SHARED: Dict[str, str] = {
        "byid": "AND rs_user.target_folder_id = $2",
        "root": "AND rs_user.target_folder_id IS NULL",
        "any":  "",
    }

    @staticmethod
    def _folder_filter_key(folder_id: Optional[str]) -> str:
        # Handler passes None (no filter), "" (root-only), or a UUID string.
        if folder_id is None:
            return "any"
        if folder_id == "":
            return "root"
        return "byid"

    async def list_workflows_org(
        self, conn, *, organization_id, user_id, folder_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Org-context list: user's own org workflows + workflows shared
        with the org + workflows in folders shared with the org."""
        key = self._folder_filter_key(folder_id)
        folder_condition = self._FOLDER_FILTERS_ORG[key]
        if key == "byid":
            params = [organization_id, user_id, folder_id]
        else:
            params = [organization_id, user_id]
        rows = await conn.fetch(f"""
            SELECT DISTINCT w.id, w.name, w.description, w.workflow, w.permissions,
                   w.created_at, w.updated_at, w.display_metadata, w.owner_id, w.folder_id,
                   COALESCE(rs.permission, rs_folder_org.permission) as share_permission,
                   COALESCE(
                       owner_au.raw_user_meta_data->>'full_name',
                       owner_au.raw_user_meta_data->>'name',
                       split_part(owner_au.email, '@', 1)
                   ) as owner_display_name
            FROM workflows w
            LEFT JOIN resource_shares rs ON rs.resource_id = w.id
                AND rs.resource_type = 'workflow'
                AND rs.target_type = 'organization'
                AND rs.target_org_id = $1
            LEFT JOIN LATERAL (
                SELECT rs_fo.permission
                FROM resource_shares rs_fo
                JOIN workflow_folders sf ON sf.id = rs_fo.resource_id
                JOIN workflow_folders wf ON wf.id = w.folder_id
                    AND (wf.id = sf.id OR wf.path LIKE sf.path || '%')
                WHERE rs_fo.resource_type = 'workflow_folder'
                  AND rs_fo.target_type = 'organization'
                  AND rs_fo.target_org_id = $1
                LIMIT 1
            ) rs_folder_org ON true
            LEFT JOIN auth.users owner_au ON owner_au.id = w.owner_id
            WHERE ((w.organization_id = $1 AND w.owner_id = $2)
               OR rs.id IS NOT NULL
               OR (rs_folder_org.permission IS NOT NULL AND rs.id IS NULL))
               AND w.deleted_at IS NULL
               {folder_condition}
            ORDER BY w.updated_at DESC
        """, *params)
        return [dict(r) for r in rows]

    async def list_workflows_personal(
        self, conn, *, user_id, folder_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Personal-context list: owned + user-shared + descendants of
        user-shared folders."""
        key = self._folder_filter_key(folder_id)
        folder_condition = self._FOLDER_FILTERS_PERSONAL_OWN[key]
        shared_folder_condition = self._FOLDER_FILTERS_PERSONAL_SHARED[key]
        if key == "byid":
            params = [user_id, folder_id]
        else:
            params = [user_id]
        rows = await conn.fetch(f"""
            SELECT DISTINCT w.id, w.name, w.description, w.workflow, w.permissions,
                   w.created_at, w.updated_at, w.display_metadata, w.owner_id, w.folder_id,
                   COALESCE(rs_user.permission, rs_folder_share.permission) as share_permission,
                   rs_user.target_folder_id as share_target_folder_id,
                   COALESCE(
                       owner_au.raw_user_meta_data->>'full_name',
                       owner_au.raw_user_meta_data->>'name',
                       split_part(owner_au.email, '@', 1)
                   ) as owner_display_name
            FROM workflows w
            LEFT JOIN resource_shares rs_org ON rs_org.resource_id = w.id
                AND rs_org.resource_type = 'workflow'
                AND rs_org.target_type = 'organization'
            LEFT JOIN resource_shares rs_user ON rs_user.resource_id = w.id
                AND rs_user.resource_type = 'workflow'
                AND rs_user.target_type = 'user'
                AND rs_user.target_user_id = $1
            LEFT JOIN LATERAL (
                SELECT rs_fs.permission
                FROM resource_shares rs_fs
                JOIN workflow_folders sf ON sf.id = rs_fs.resource_id
                JOIN workflow_folders wf ON wf.id = w.folder_id
                    AND (wf.id = sf.id OR wf.path LIKE sf.path || '%')
                WHERE rs_fs.resource_type = 'workflow_folder'
                  AND rs_fs.target_type = 'user'
                  AND rs_fs.target_user_id = $1
                LIMIT 1
            ) rs_folder_share ON true
            LEFT JOIN auth.users owner_au ON owner_au.id = w.owner_id
            WHERE (
                (w.owner_id = $1 AND w.organization_id IS NULL AND rs_org.id IS NULL {folder_condition})
                OR
                (rs_user.id IS NOT NULL AND w.owner_id != $1 {shared_folder_condition})
                OR
                (rs_folder_share.permission IS NOT NULL AND w.owner_id != $1 AND rs_user.id IS NULL {folder_condition})
            )
            AND w.deleted_at IS NULL
            ORDER BY w.updated_at DESC
        """, *params)
        return [dict(r) for r in rows]

    async def list_workflows_builder(
        self, conn, *, user_id: UUID, organization_id: Optional[UUID],
        query: Optional[str], limit: int,
    ) -> List[Dict[str, Any]]:
        """Builder platform_ops list — a simpler search-only query used by
        the AI builder to surface workflow suggestions. Org context returns
        user's org-scoped rows + org-shared; personal returns owned-personal."""
        params: List[Any]
        if organization_id is not None:
            conditions = [
                "((w.organization_id = $1 AND w.owner_id = $2) OR rs.id IS NOT NULL)",
                "w.deleted_at IS NULL",
            ]
            params = [organization_id, user_id]
            idx = 3
            join = (
                "LEFT JOIN resource_shares rs ON rs.resource_id = w.id "
                "AND rs.resource_type = 'workflow' "
                "AND rs.target_type = 'organization' "
                "AND rs.target_org_id = $1"
            )
        else:
            conditions = [
                "(w.owner_id = $1 AND w.organization_id IS NULL)",
                "w.deleted_at IS NULL",
            ]
            params = [user_id]
            idx = 2
            join = ""

        if query:
            search = f"(w.name ILIKE ${idx} OR w.description ILIKE ${idx}"
            params.append(f"%{query}%")
            idx += 1
            # A query that IS a workflow id matches by id too — the builder's
            # recovery path passes a bare id and would otherwise find nothing.
            query_uuid = _try_parse_uuid(query)
            if query_uuid is not None:
                search += f" OR w.id = ${idx}"
                params.append(query_uuid)
                idx += 1
            conditions.append(search + ")")

        params.append(limit)
        where = " AND ".join(f"({c})" for c in conditions)
        rows = await conn.fetch(
            f"""SELECT DISTINCT w.id, w.name, w.description, w.updated_at
                FROM workflows w
                {join}
                WHERE {where}
                ORDER BY w.updated_at DESC LIMIT ${idx}""",
            *params,
        )
        return [dict(r) for r in rows]

    async def list_workflows_mcp(
        self, conn, *, user_id: str, query: Optional[str],
        folder_id: Optional[str], limit: int,
    ) -> List[Dict[str, Any]]:
        """MCP ``list_workflows`` — user-owned only (via user_id column),
        with optional name/description ILIKE search and folder filter."""
        conditions = ["user_id = $1", "deleted_at IS NULL"]
        params: List[Any] = [user_id]
        idx = 2

        if query:
            search_pattern = f"%{query}%"
            search = f"(name ILIKE ${idx} OR description ILIKE ${idx}"
            params.append(search_pattern)
            idx += 1
            # A query that IS a workflow id matches by id too (see builder note).
            query_uuid = _try_parse_uuid(query)
            if query_uuid is not None:
                search += f" OR id = ${idx}"
                params.append(query_uuid)
                idx += 1
            conditions.append(search + ")")

        if folder_id is not None:
            if folder_id == "":
                conditions.append("folder_id IS NULL")
            else:
                conditions.append(f"folder_id = ${idx}")
                params.append(folder_id)
                idx += 1

        params.append(limit)
        where_clause = " AND ".join(conditions)
        rows = await conn.fetch(f"""
            SELECT id, name, description, folder_id, created_at, updated_at
            FROM workflows
            WHERE {where_clause}
            ORDER BY updated_at DESC
            LIMIT ${idx}
        """, *params)
        return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════════════════════════
    # Workflow JSONB / node operations
    # ══════════════════════════════════════════════════════════════════════

    async def get_node_type_and_operation(
        self, conn, workflow_id, node_id: str
    ) -> Optional[Dict[str, Any]]:
        """Read the node's ``type`` + current ``config.operation`` from the
        workflow blob — used before merging a new config so the caller can
        detect operation changes and clean up orphaned webhooks."""
        row = await conn.fetchrow("""
            SELECT node->>'type' AS node_type,
                   node->'config'->>'operation' AS old_operation
            FROM workflows,
                 jsonb_array_elements(workflow->'nodes') AS node
            WHERE workflows.id = $1 AND node->>'id' = $2
            LIMIT 1
        """, workflow_id, node_id)
        return dict(row) if row else None

    async def merge_node_config(
        self, conn, workflow_id, node_id: str, config_delta: Dict[str, Any]
    ) -> str:
        """Atomic merge of ``config_delta`` into the target node's config
        via a CTE + jsonb_set. Returns the asyncpg command tag so the
        caller can surface "node not found" via ``UPDATE 0``."""
        return await conn.execute("""
            WITH target AS (
                SELECT (idx - 1)::int AS pos
                FROM jsonb_array_elements(
                    (SELECT workflow->'nodes' FROM workflows WHERE id = $1)
                ) WITH ORDINALITY AS n(node, idx)
                WHERE node->>'id' = $2
                LIMIT 1
            )
            UPDATE workflows
            SET workflow = jsonb_set(
                workflow,
                ARRAY['nodes', target.pos::text, 'config'],
                COALESCE(workflow->'nodes'->target.pos->'config', '{}'::jsonb) || $3::jsonb
            ),
            updated_at = now()
            FROM target
            WHERE workflows.id = $1
        """, workflow_id, node_id, config_delta)

    async def strip_node_config_keys(
        self, conn, workflow_id, node_id: str, keys: List[str]
    ) -> None:
        """Remove a fixed set of keys from the target node's config JSONB.
        Used after an operation change to drop stale webhook/poll fields."""
        await conn.execute("""
            WITH target AS (
                SELECT (idx - 1)::int AS pos
                FROM jsonb_array_elements(
                    (SELECT workflow->'nodes' FROM workflows WHERE id = $1)
                ) WITH ORDINALITY AS n(node, idx)
                WHERE node->>'id' = $2
                LIMIT 1
            )
            UPDATE workflows
            SET workflow = jsonb_set(
                workflow,
                ARRAY['nodes', target.pos::text, 'config'],
                (workflow->'nodes'->target.pos->'config') - $3::text[]
            ),
            updated_at = now()
            FROM target
            WHERE workflows.id = $1
        """, workflow_id, node_id, keys)

    async def merge_workflow_variables(
        self, conn, workflow_id, var_updates: Dict[str, Any]
    ) -> None:
        """Mirror set-variable node outputs into the workflow's
        ``variables`` JSONB. Uses ``jsonb_set`` on the ``{variables}``
        path so it never clobbers concurrent edits to other blob fields."""
        await conn.execute(
            """
            UPDATE workflows
            SET workflow = jsonb_set(
                    workflow, '{variables}',
                    COALESCE(workflow->'variables', '{}'::jsonb) || $1::jsonb, true),
                updated_at = NOW()
            WHERE id = $2
            """,
            var_updates, workflow_id,
        )

    # ══════════════════════════════════════════════════════════════════════
    # workflow_node_state
    # ══════════════════════════════════════════════════════════════════════

    async def delete_node_state(
        self, conn, workflow_id: UUID, node_id: str
    ) -> int:
        """Delete a node's state row. Returns the number of rows deleted
        (parsed from the asyncpg command tag)."""
        result = await conn.execute("""
            DELETE FROM workflow_node_state
            WHERE workflow_id = $1 AND node_id = $2
        """, workflow_id, node_id)
        return int(result.split()[-1]) if result else 0

    async def upsert_node_state(
        self, conn, workflow_id: UUID, node_id: str, values: Any
    ) -> None:
        """Save persistent state for a node (SDK state.set for non-null values)."""
        await conn.execute("""
            INSERT INTO workflow_node_state (id, workflow_id, node_id, state, created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $2, $3::jsonb, NOW(), NOW())
            ON CONFLICT (workflow_id, node_id)
            DO UPDATE SET state = $3::jsonb, updated_at = NOW()
        """, workflow_id, node_id, values)

    async def get_node_state(
        self, conn, workflow_id: UUID, node_id: str
    ) -> Optional[Any]:
        """Return the raw ``state`` cell (jsonb) or None."""
        row = await conn.fetchrow("""
            SELECT state FROM workflow_node_state
            WHERE workflow_id = $1 AND node_id = $2
        """, workflow_id, node_id)
        return row['state'] if row else None

    async def delete_state_key(
        self, conn, workflow_id: UUID, node_id: str, key: str
    ) -> None:
        """Drop a key from state (SDK state.delete). Uses the JSONB minus
        operator so keys() no longer lists the tombstone."""
        await conn.execute("""
            UPDATE workflow_node_state
            SET state = COALESCE(state, '{}'::jsonb) - $3
            WHERE workflow_id = $1 AND node_id = $2
        """, workflow_id, node_id, key)

    async def merge_state_key(
        self, conn, workflow_id: UUID, node_id: str, patch: Dict[str, Any]
    ) -> None:
        """Atomic upsert-merge of a single key into an existing state (SDK
        state.set with non-null value)."""
        await conn.execute("""
            INSERT INTO workflow_node_state (workflow_id, node_id, state)
            VALUES ($1, $2, $3)
            ON CONFLICT (workflow_id, node_id) DO UPDATE
            SET state = COALESCE(workflow_node_state.state, '{}'::jsonb) || $3
        """, workflow_id, node_id, patch)

    # ══════════════════════════════════════════════════════════════════════
    # workflow_executions
    # ══════════════════════════════════════════════════════════════════════

    async def create_execution(
        self,
        conn,
        *,
        workflow_id,
        user_id,
        trigger_source: str,
    ) -> str:
        """Create a ``running`` execution row and return the new id (str)."""
        row = await conn.fetchrow("""
            INSERT INTO workflow_executions (workflow_id, user_id, status, started_at, nodes_executed, trigger_source)
            VALUES ($1, $2, 'running', NOW(), 0, $3)
            RETURNING id
        """, workflow_id, user_id, trigger_source)
        return str(row['id'])

    async def list_executions(
        self,
        conn,
        *,
        workflow_id,
        status_filter: Optional[List[str]],
        trigger_filter: Optional[List[str]],
        search: Optional[str],
        cursor_ts: Optional[Any],
        cursor_id: Optional[Any],
        limit: int,
        from_ts: Optional[Any] = None,
        to_ts: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Cursor-paginated execution log — served by the covering index
        ``idx_workflow_executions_workflow_started``. Optional from_ts/to_ts
        bound the started_at range (NULL = unbounded)."""
        rows = await conn.fetch("""
            SELECT id, workflow_id, user_id, status, started_at, finished_at,
                   nodes_executed, error, trigger_source, graph_hash
            FROM workflow_executions
            WHERE workflow_id = $1
              AND ($2::text[] IS NULL OR status = ANY($2::text[]))
              AND ($3::text[] IS NULL OR trigger_source = ANY($3::text[]))
              AND ($4::text IS NULL OR error ILIKE '%' || $4::text || '%')
              AND (
                  $5::timestamptz IS NULL
                  OR ROW(started_at, id) < ROW($5::timestamptz, $6::uuid)
              )
              AND ($8::timestamptz IS NULL OR started_at >= $8::timestamptz)
              AND ($9::timestamptz IS NULL OR started_at <= $9::timestamptz)
            ORDER BY started_at DESC, id DESC
            LIMIT $7
        """,
            workflow_id, status_filter, trigger_filter, search,
            cursor_ts, cursor_id, limit, from_ts, to_ts,
        )
        return [dict(r) for r in rows]

    async def execution_counts(
        self, conn, workflow_id
    ) -> List[Dict[str, Any]]:
        """GROUPING SETS aggregate for the workflow's execution counts (total
        + per-status + per-trigger). Index-Only Scan at prod scale."""
        rows = await conn.fetch("""
            SELECT GROUPING(status, trigger_source) AS gid,
                   status,
                   trigger_source,
                   count(*) AS n
            FROM workflow_executions
            WHERE workflow_id = $1
            GROUP BY GROUPING SETS ((status), (trigger_source), ())
        """, workflow_id)
        return [dict(r) for r in rows]

    async def get_execution_detail(
        self, conn, execution_id, workflow_id
    ) -> Optional[Dict[str, Any]]:
        """Single-row detail for the ``get_execution_detail`` view."""
        row = await conn.fetchrow("""
            SELECT id, workflow_id, user_id, status, started_at, finished_at,
                   nodes_executed, error, trigger_source, graph_hash
            FROM workflow_executions WHERE id = $1 AND workflow_id = $2
        """, execution_id, workflow_id)
        return dict(row) if row else None

    async def get_execution_status(
        self, conn, execution_id
    ) -> Optional[str]:
        """Just the ``status`` cell — used by ``_is_execution_suspended``."""
        row = await conn.fetchrow(
            "SELECT status FROM workflow_executions WHERE id = $1",
            execution_id,
        )
        return row["status"] if row else None

    async def get_execution_by_id_and_user(
        self, conn, execution_id, user_id
    ) -> Optional[Dict[str, Any]]:
        """MCP ``get_execution_status`` by ``execution_id``."""
        row = await conn.fetchrow("""
            SELECT id, workflow_id, status, started_at, finished_at, nodes_executed, error
            FROM workflow_executions
            WHERE id = $1 AND user_id = $2
        """, execution_id, user_id)
        return dict(row) if row else None

    async def get_latest_execution_by_workflow_and_user(
        self, conn, workflow_id, user_id
    ) -> Optional[Dict[str, Any]]:
        """MCP ``get_execution_status`` by ``workflow_id`` (latest run)."""
        row = await conn.fetchrow("""
            SELECT id, workflow_id, status, started_at, finished_at, nodes_executed, error
            FROM workflow_executions
            WHERE workflow_id = $1 AND user_id = $2
            ORDER BY started_at DESC
            LIMIT 1
        """, workflow_id, user_id)
        return dict(row) if row else None

    async def get_latest_finished_execution_status(
        self, conn, workflow_id
    ) -> Optional[Dict[str, Any]]:
        """Latest non-running execution — builder ``run_node`` reads this to
        classify a failed run."""
        row = await conn.fetchrow(
            """SELECT status, error FROM workflow_executions
               WHERE workflow_id = $1 AND status != 'running'
               ORDER BY finished_at DESC NULLS LAST LIMIT 1""",
            workflow_id,
        )
        return dict(row) if row else None

    async def delete_execution(
        self, conn, execution_id
    ) -> None:
        """Delete an execution row — used for no-op Drive/Calendar
        wake-ups so they don't appear in run history."""
        await conn.execute(
            "DELETE FROM workflow_executions WHERE id = $1", execution_id,
        )

    async def mark_execution_completed(
        self, conn, execution_id, nodes_executed: int
    ) -> None:
        """Terminal state = completed."""
        await conn.execute("""
            UPDATE workflow_executions
            SET status = 'completed', finished_at = NOW(), nodes_executed = $1
            WHERE id = $2
        """, nodes_executed, execution_id)

    async def mark_execution_completed_empty(
        self, conn, execution_id
    ) -> None:
        """Empty-workflow completion (nodes_executed=0)."""
        await conn.execute("""
            UPDATE workflow_executions
            SET status = 'completed', finished_at = NOW(), nodes_executed = 0
            WHERE id = $1
        """, execution_id)

    async def mark_execution_error(
        self, conn, execution_id, nodes_executed: int, error: str
    ) -> None:
        """Terminal state = error, with nodes_executed count."""
        await conn.execute("""
            UPDATE workflow_executions
            SET status = 'error', finished_at = NOW(), nodes_executed = $1, error = $2
            WHERE id = $3
        """, nodes_executed, error, execution_id)

    async def mark_execution_error_simple(
        self, conn, execution_id, error: str
    ) -> None:
        """Terminal error state without touching nodes_executed (used from
        the outer exception handler where we don't know how many nodes
        ran)."""
        await conn.execute("""
            UPDATE workflow_executions
            SET status = 'error', finished_at = NOW(), error = $1
            WHERE id = $2
        """, error, execution_id)

    async def mark_execution_error_at_startup(
        self, conn, execution_id, error: str
    ) -> None:
        """Terminal error state from the cycle-detection path (nodes_executed
        stays at the value already stored by the startup path)."""
        await conn.execute("""
            UPDATE workflow_executions
            SET status = 'error', finished_at = NOW(), error = $1
            WHERE id = $2
        """, error, execution_id)

    async def reap_stale_running_executions(
        self, conn, *, max_age_hours: int = 6
    ) -> int:
        """Flip abandoned ``running`` rows to error. A row can only stay
        ``running`` past its real lifetime when the run loop died without
        finalizing (container OOM/restart, or an engine bug stranding the
        gather). Suspended runs are excluded by construction: approval/delay
        write ``status='awaiting_*'`` WITH ``finished_at`` set, never
        ``running``/NULL. Returns the number of rows reaped."""
        result = await conn.execute("""
            UPDATE workflow_executions
            SET status = 'error', finished_at = NOW(),
                error = 'Execution was abandoned without finishing (system interruption)'
            WHERE status = 'running'
              AND finished_at IS NULL
              AND started_at < NOW() - make_interval(hours => $1)
        """, max_age_hours)
        return int(result.split()[-1] or 0)

    async def resume_execution_running(
        self, conn, execution_id: UUID
    ) -> None:
        """Flip an execution back to running when a paused (approval/delay)
        run resumes."""
        await conn.execute(
            """UPDATE workflow_executions
               SET status = 'running', finished_at = NULL
               WHERE id = $1""",
            execution_id,
        )

    async def complete_no_downstream_resume(
        self, conn, execution_id: UUID, from_status: str
    ) -> None:
        """Resume path with no downstream nodes — flip to completed only if
        still in the expected suspended status (defensive against another
        writer)."""
        await conn.execute(
            "UPDATE workflow_executions SET status = 'completed', finished_at = NOW() "
            "WHERE id = $1 AND status = $2",
            execution_id, from_status,
        )

    async def finalize_resume_completed(
        self, conn, execution_id: UUID, nodes_executed_delta: int
    ) -> None:
        """Resume terminal-success write — additive nodes_executed."""
        await conn.execute(
            """UPDATE workflow_executions
               SET status = 'completed', finished_at = NOW(),
                   nodes_executed = nodes_executed + $1
               WHERE id = $2""",
            nodes_executed_delta, execution_id,
        )

    async def finalize_resume_error(
        self, conn, execution_id: UUID, nodes_executed_delta: int, error: str
    ) -> None:
        """Resume terminal-error write — additive nodes_executed + error."""
        await conn.execute(
            """UPDATE workflow_executions
               SET status = 'error', finished_at = NOW(),
                   nodes_executed = nodes_executed + $1, error = $2
               WHERE id = $3""",
            nodes_executed_delta, error, execution_id,
        )

    async def list_tool_calls_for_execution(
        self, conn, execution_id
    ) -> List[Dict[str, Any]]:
        """Agent tool calls made during a run — recorded by
        ``tool_execution.execute_tool`` and rendered in the log viewer.
        Kept in WorkflowRepo because it's a per-execution read that lives
        alongside every other execution-detail query."""
        rows = await conn.fetch("""
            SELECT agent_node_id, tool_name, tool_type, provider_node_id,
                   operation, credential_id, arguments, result_status,
                   error, result_preview, duration_ms, created_at
            FROM tool_call_events
            WHERE execution_id = $1
            ORDER BY created_at
        """, execution_id)
        return [dict(r) for r in rows]

    async def list_cas_manifest_status(
        self, conn, execution_id, workflow_id
    ) -> List[Dict[str, Any]]:
        """Per-node last-run status + whether an output manifest is
        present — powers the execution-detail badges. Reads from
        ``cas_manifests`` but scoped by the execution + workflow so it
        naturally belongs with the other execution-detail queries."""
        rows = await conn.fetch("""
            SELECT node_id, last_run_status, last_run_error, (manifest IS NOT NULL) AS has_output
            FROM cas_manifests WHERE execution_id = $1 AND workflow_id = $2
            ORDER BY created_at ASC
        """, execution_id, workflow_id)
        return [dict(r) for r in rows]

    # ══════════════════════════════════════════════════════════════════════
    # workflow_checkpoints
    # ══════════════════════════════════════════════════════════════════════

    async def create_checkpoint(
        self,
        conn,
        *,
        user_id,
        workflow_id,
        name: str,
        description: str,
        workflow_data: Any,
    ) -> Optional[Dict[str, Any]]:
        """Insert a new checkpoint. Handler has already checked access and
        the per-workflow cap. Returns the columns the response echoes back."""
        row = await conn.fetchrow("""
            INSERT INTO workflow_checkpoints
                (user_id, workflow_id, name, description, workflow, created_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            RETURNING id, workflow_id, name, description, created_at
        """, user_id, workflow_id, name, description, workflow_data)
        return dict(row) if row else None

    async def list_checkpoints(
        self, conn, workflow_id
    ) -> List[Dict[str, Any]]:
        """All checkpoints for a workflow — the endpoint returns everyone's
        checkpoints (access already gated by the calling handler)."""
        rows = await conn.fetch("""
            SELECT id, workflow_id, name, description, created_at
            FROM workflow_checkpoints
            WHERE workflow_id = $1
            ORDER BY created_at DESC
        """, workflow_id)
        return [dict(r) for r in rows]

    async def get_checkpoint_and_current(
        self, conn, checkpoint_id, workflow_id
    ) -> Optional[Dict[str, Any]]:
        """Fetch the checkpoint's stored blob AND the workflow's current
        blob in one round-trip so the caller can compute the node-diff for
        webhook/cron cleanup vs restore."""
        row = await conn.fetchrow("""
            SELECT c.workflow as checkpoint_workflow, w.workflow as current_workflow
            FROM workflow_checkpoints c
            JOIN workflows w ON w.id = c.workflow_id
            WHERE c.id = $1 AND c.workflow_id = $2
        """, checkpoint_id, workflow_id)
        return dict(row) if row else None

    async def restore_workflow_from_checkpoint(
        self, conn, workflow_id, workflow_data: Any
    ) -> None:
        """Replace the workflow's blob with the checkpoint's saved blob.
        Kept distinct from ``replace_workflow_data`` so the caller reads
        as intent."""
        await conn.execute("""
            UPDATE workflows
            SET workflow = $1, updated_at = NOW()
            WHERE id = $2
        """, workflow_data, workflow_id)

    async def delete_checkpoint(
        self, conn, checkpoint_id, user_id
    ) -> str:
        """Owner-gated delete (checkpoint's own ``user_id``). Returns the
        command tag so the caller can distinguish not-found from deleted."""
        return await conn.execute("""
            DELETE FROM workflow_checkpoints
            WHERE id = $1 AND user_id = $2
        """, checkpoint_id, user_id)

    # ══════════════════════════════════════════════════════════════════════
    # workflow_folders (owner-scoped, builder platform_ops)
    # ──────────────────────────────────────────────────────────────────────
    # OrgRepo owns the rich org-context / personal-with-shared folder
    # queries. These variants are the SIMPLER owner-scoped ones the
    # builder platform_ops uses — a hand-built agent operating on the
    # actor's own workspace only. Kept here so the WorkflowRepo covers
    # every SQL the builder handler emits.
    # ══════════════════════════════════════════════════════════════════════

    async def list_builder_folders_org(
        self, conn, organization_id: UUID, user_id: UUID
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            """SELECT f.id, f.name, f.parent_folder_id,
                      (SELECT count(*) FROM workflows w WHERE w.folder_id = f.id AND w.deleted_at IS NULL) as workflow_count
               FROM workflow_folders f
               WHERE f.organization_id = $1 AND f.owner_id = $2
               ORDER BY f.depth, f.name""",
            organization_id, user_id,
        )
        return [dict(r) for r in rows]

    async def list_builder_folders_personal(
        self, conn, user_id: UUID
    ) -> List[Dict[str, Any]]:
        rows = await conn.fetch(
            """SELECT f.id, f.name, f.parent_folder_id,
                      (SELECT count(*) FROM workflows w WHERE w.folder_id = f.id AND w.deleted_at IS NULL) as workflow_count
               FROM workflow_folders f
               WHERE f.owner_id = $1 AND f.organization_id IS NULL
               ORDER BY f.depth, f.name""",
            user_id,
        )
        return [dict(r) for r in rows]

    # Folder access/permission reads live in OrgRepo (``can_access_folder``,
    # ``get_folder_owner``, ``get_folder_owner_and_parent``) — one SQL home.

    async def insert_folder_builder(
        self,
        conn,
        *,
        name: str,
        owner_id: UUID,
        organization_id: Optional[UUID],
        parent_folder_id: Optional[UUID],
    ) -> Any:
        """Insert a folder from the builder path — returns the id."""
        return await conn.fetchval(
            """INSERT INTO workflow_folders (name, owner_id, organization_id, parent_folder_id)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            name, owner_id, organization_id, parent_folder_id,
        )

    async def hoist_workflows_to_parent(
        self, conn, folder_id: UUID, new_parent_folder_id: Optional[UUID]
    ) -> None:
        """Reparent workflows before folder delete so they aren't lost."""
        await conn.execute(
            "UPDATE workflows SET folder_id = $1 WHERE folder_id = $2",
            new_parent_folder_id, folder_id,
        )

    async def delete_folder(
        self, conn, folder_id: UUID
    ) -> None:
        """DELETE — cascade handles child folder rows."""
        await conn.execute(
            "DELETE FROM workflow_folders WHERE id = $1",
            folder_id,
        )

    async def set_workflow_folder(
        self, conn, workflow_id: UUID, folder_id: Optional[UUID]
    ) -> None:
        """Move a workflow to a folder (or root if ``folder_id`` is None)."""
        await conn.execute(
            "UPDATE workflows SET folder_id = $1 WHERE id = $2",
            folder_id, workflow_id,
        )
