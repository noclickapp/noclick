"""CredentialsRepo — SQL for the credentials + credential_requests domain.

Owns every direct SELECT/INSERT/UPDATE/DELETE that ``credentials_handler``
used to inline. Encryption of the ``credential`` blob stays in the handler —
the blob is opaque to this repo. Repo methods return typed dataclasses / bool
/ Optional[dataclass] so callers never touch ``asyncpg.Record``.

Handler methods that call cross-cutting helpers still living in other
modules (``get_user_org_context``/``get_context_tier`` — both take an
explicit ``conn``) keep their own ``async with pool.acquire()`` block for
those specific calls. ``create_credential_with_limit_check`` lives HERE —
the INSERT is repo business; only the limit check itself stays in billing.

See ``backend/utils/DB_MIGRATION.md`` for the seven rules; ``UsageRepo``
is the reference implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from utils.analytics import log_activity_background
from utils.analytics_events import Events

from .organization import PRIMARY_ORG_SQL


def credential_access_predicate(require_edit: bool = False) -> str:
    """THE credential access boundary — owner, direct user-share, or org-share
    on ``resource_shares`` — as a WHERE fragment over ``credentials c``.

    Placeholders are fixed: $2 = user_id, $3 = org_id (nullable uuid). The
    credential id binds through ``c.id``, which the caller pins itself
    (``c.id = $1`` or ``c.id = ANY($1::uuid[])``). ``require_edit`` narrows
    both share branches to edit-permission shares. Compose from this —
    never copy the predicate.
    """
    edit = "\n                AND permission = 'edit'" if require_edit else ""
    return f"""(
            c.owner_id = $2
            OR EXISTS (
              SELECT 1 FROM resource_shares
              WHERE resource_type = 'credential'
                AND resource_id = c.id
                AND target_type = 'user'
                AND target_user_id = $2{edit}
            )
            OR ($3::uuid IS NOT NULL AND EXISTS (
              SELECT 1 FROM resource_shares
              WHERE resource_type = 'credential'
                AND resource_id = c.id
                AND target_type = 'organization'
                AND target_org_id = $3{edit}
            ))
          )"""


@dataclass(frozen=True)
class PendingTransfer:
    """One credential_request row that survived the fulfilled-and-still-
    requester-owned check in _transfer_provided_credentials."""
    request_id: str
    credential_id: str
    requester_id: str


@dataclass(frozen=True)
class AccessibleCredential:
    """Row shape returned by ``list_accessible`` — everything the credential
    dropdown needs to render (metadata, ownership, share info, revocation
    state — a revoked credential must be visibly dead in the picker, not
    indistinguishable from a live one)."""
    id: str
    name: str
    credential_type: str
    metadata: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    owner_id: str
    organization_id: Optional[str]
    access_type: str
    my_permission: str
    sort_order: int
    owner_email: Optional[str]
    owner_name: Optional[str]
    share_id: Optional[str]
    shared_with_org: bool
    revoked_at: Optional[datetime]
    revoked_reason: Optional[str]


@dataclass(frozen=True)
class WorkflowOwnerAndBlob:
    """Minimal workflow row for the display_info gate."""
    workflow: Any
    owner_id: str


@dataclass(frozen=True)
class CredentialDisplayRow:
    """Display-only credential shape for the collaborative display_info path.
    Never carries the encrypted blob."""
    id: str
    name: str
    credential_type: str
    owner_id: str
    owner_email: Optional[str]
    owner_name: Optional[str]


@dataclass(frozen=True)
class CredentialWithBlob:
    """Full credential row including the encrypted blob — used by get_credential."""
    id: str
    name: str
    credential_type: str
    credential: str
    metadata: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CredentialRow:
    """Bare credential row (no blob) returned after update/fetch-fallback."""
    id: str
    name: str
    credential_type: str
    metadata: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CredentialTypeAndBlob:
    """Slice of a credential needed for provider-side token revocation on delete."""
    credential_type: str
    credential: str
    organization_id: Optional[str] = None


@dataclass(frozen=True)
class CredentialRequestRow:
    """One credential_requests row shaped for wire responses.

    ``token`` is only populated on the upsert path (needed to compose the
    request email); list/cancel paths never read it.
    """
    id: str
    target_email: str
    credential_type: str
    message: Optional[str]
    status: str
    credential_id: Optional[str]
    expires_at: Optional[datetime]
    created_at: datetime
    fulfilled_at: Optional[datetime]
    token: Optional[str] = None


class CredentialsRepo:
    """Read/write SQL for the credentials + credential_requests tables.

    Constructor takes a pool proxy from ``DatabasePoolMixin.get_pool()``.
    Every method acquires a real pinned connection for the duration of its
    work. Multi-statement writes wrap the acquire in a real transaction so
    partial failures roll back.
    """

    # Columns the update_metadata_or_fetch path is allowed to interpolate
    # into UPDATE ... SET. Defense-in-depth: the handler only ever passes
    # these two, but the check refuses anything outside the set even if a
    # caller drifts.
    _ALLOWED_UPDATE_COLS = frozenset({"name", "metadata"})

    def __init__(self, pool):
        self._pool = pool

    # ------------------------------------------------------------------
    # _transfer_provided_credentials
    # ------------------------------------------------------------------

    async def list_pending_transfers(self, target_email: str) -> List[PendingTransfer]:
        """Fulfilled credential_requests whose credential is still owned by
        the original requester — i.e. the target user just signed up and we
        need to transfer ownership to them."""
        sql = """
            SELECT cr.id, cr.credential_id, cr.requester_id
            FROM credential_requests cr
            JOIN credentials c ON c.id = cr.credential_id
            WHERE cr.target_email = LOWER($1)
              AND cr.status = 'fulfilled'
              AND cr.credential_id IS NOT NULL
              AND c.owner_id = cr.requester_id
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, target_email)
        return [
            PendingTransfer(
                request_id=str(r['id']),
                credential_id=str(r['credential_id']),
                requester_id=str(r['requester_id']),
            )
            for r in rows
        ]

    async def transfer_credential_ownership(
        self,
        *,
        credential_id: str,
        new_owner_id: str,
        requester_id: str,
    ) -> None:
        """Atomically re-parent a credential to the new owner AND grant the
        original requester an edit share so their workflow keeps working.

        Wrapped in a transaction so an orphan owner-change without the
        matching share (or vice versa) can't leak on partial failure."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE credentials SET owner_id = $1 WHERE id = $2",
                    new_owner_id, credential_id,
                )
                await conn.execute(
                    """
                    INSERT INTO resource_shares (
                        resource_type, resource_id, target_type,
                        target_user_id, permission, shared_by
                    )
                    VALUES ('credential', $1, 'user', $2, 'edit', $3)
                    ON CONFLICT DO NOTHING
                    """,
                    str(credential_id), str(requester_id), new_owner_id,
                )

    # ------------------------------------------------------------------
    # list_credentials
    # ------------------------------------------------------------------

    _LIST_ACCESSIBLE_SQL = """
        SELECT DISTINCT ON (c.id)
            c.id, c.name, c.credential_type, c.metadata, c.created_at, c.updated_at,
            c.owner_id, c.organization_id, c.revoked_at, c.revoked_reason,
            CASE
                WHEN c.owner_id = $1 THEN 'owner'
                WHEN us.id IS NOT NULL AND os.id IS NOT NULL THEN 'shared'
                WHEN us.id IS NOT NULL THEN 'shared'
                WHEN os.id IS NOT NULL THEN 'shared_org'
                ELSE 'shared'
            END as access_type,
            CASE
                WHEN c.owner_id = $1 THEN 'edit'
                WHEN us.permission = 'edit' OR os.permission = 'edit' THEN 'edit'
                ELSE 'view'
            END as my_permission,
            CASE WHEN c.owner_id = $1 THEN 0 ELSE 1 END as sort_order,
            owner.email as owner_email,
            owner.raw_user_meta_data->>'name' as owner_name,
            COALESCE(us.id, os.id) as share_id,
            (os.id IS NOT NULL) as shared_with_org
        FROM credentials c
        LEFT JOIN resource_shares us
            ON us.resource_type = 'credential'
            AND us.resource_id = c.id
            AND us.target_type = 'user'
            AND us.target_user_id = $1
        LEFT JOIN resource_shares os
            ON os.resource_type = 'credential'
            AND os.resource_id = c.id
            AND os.target_type = 'organization'
            AND os.target_org_id = $2
        LEFT JOIN auth.users owner ON owner.id = c.owner_id
        WHERE
            c.owner_id = $1
            OR us.id IS NOT NULL
            OR ($2::uuid IS NOT NULL AND os.id IS NOT NULL)
        ORDER BY c.id, sort_order, c.created_at DESC
    """

    async def list_accessible(
        self, user_id: str, org_id: Optional[str]
    ) -> List[AccessibleCredential]:
        """Every credential the user can see: owned + shared-directly +
        (in org context only) shared-with-current-org. Sort order in the
        result is by-id-then-first-match; the caller re-sorts by
        (sort_order, created_at desc) — that ranking logic stays in the
        handler because it drives the cap enforcement passes."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(self._LIST_ACCESSIBLE_SQL, user_id, org_id)
        return [
            AccessibleCredential(
                id=str(r['id']),
                name=r['name'],
                credential_type=r['credential_type'],
                metadata=r['metadata'],
                created_at=r['created_at'],
                updated_at=r['updated_at'],
                owner_id=str(r['owner_id']),
                organization_id=str(r['organization_id']) if r['organization_id'] else None,
                access_type=r['access_type'],
                my_permission=r['my_permission'],
                sort_order=r['sort_order'],
                owner_email=r['owner_email'],
                owner_name=r['owner_name'],
                share_id=str(r['share_id']) if r['share_id'] else None,
                shared_with_org=bool(r['shared_with_org']),
                revoked_at=r['revoked_at'],
                revoked_reason=r['revoked_reason'],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # display_info
    # ------------------------------------------------------------------

    async def fetch_workflow_owner_and_blob(
        self, workflow_id: str
    ) -> Optional[WorkflowOwnerAndBlob]:
        """Minimal workflow row for the credential-display gate. Returns
        ``None`` if the workflow doesn't exist or was soft-deleted."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT workflow, owner_id FROM workflows WHERE id = $1 AND deleted_at IS NULL",
                workflow_id,
            )
        if not row:
            return None
        return WorkflowOwnerAndBlob(
            workflow=row['workflow'],
            owner_id=str(row['owner_id']),
        )

    async def fetch_credentials_display_info(
        self, credential_ids: List[str], owner_id: str
    ) -> List[CredentialDisplayRow]:
        """Display-only credential rows for a workflow, constrained to the
        workflow owner's credentials — a collaborator can't inject arbitrary
        UUIDs and read back a third party's credential name."""
        if not credential_ids:
            return []
        sql = """
            SELECT c.id, c.name, c.credential_type, c.owner_id,
                   u.email AS owner_email,
                   u.raw_user_meta_data->>'name' AS owner_name
            FROM credentials c
            JOIN auth.users u ON u.id = c.owner_id
            WHERE c.id = ANY($1::uuid[]) AND c.owner_id = $2
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, credential_ids, owner_id)
        return [
            CredentialDisplayRow(
                id=str(r['id']),
                name=r['name'],
                credential_type=r['credential_type'],
                owner_id=str(r['owner_id']),
                owner_email=r['owner_email'],
                owner_name=r['owner_name'],
            )
            for r in rows
        ]

    async def fetch_health_probe_rows(
        self, credential_ids: List[str], credential_types: Optional[List[str]] = None
    ) -> List[CredentialRow]:
        """Metadata-only rows for provider-session health checks
        (utils.credential_health). No blob, no owner join — the ids come from a
        workflow graph the caller already has access to, and nothing secret is
        read. ``credential_types`` narrows to health-checked types so rows the
        checker would discard are never shipped."""
        if not credential_ids:
            return []
        sql = """
            SELECT id, name, credential_type, metadata, created_at, updated_at
            FROM credentials WHERE id = ANY($1::uuid[])
              AND ($2::text[] IS NULL OR credential_type = ANY($2::text[]))
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, credential_ids, credential_types)
        return [
            CredentialRow(
                id=str(r['id']),
                name=r['name'],
                credential_type=r['credential_type'],
                metadata=r['metadata'],
                created_at=r['created_at'],
                updated_at=r['updated_at'],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # authorize_for_workflow
    # ------------------------------------------------------------------

    async def is_owner(self, credential_id: str, owner_id: str) -> bool:
        """Lightweight ownership check — no decrypt. The authorize path uses
        this to keep the workflow's authorized set free of credentials the
        purported owner doesn't actually own (which would be inert at
        resolution anyway)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT 1 FROM credentials WHERE id = $1::uuid AND owner_id = $2::uuid",
                credential_id, owner_id,
            )
        return row is not None

    # ------------------------------------------------------------------
    # get_credential
    # ------------------------------------------------------------------

    _FETCH_WITH_ACCESS_SQL = f"""
        SELECT c.id, c.name, c.credential_type, c.credential, c.metadata, c.created_at, c.updated_at
        FROM credentials c
        WHERE c.id = $1
          AND {credential_access_predicate()}
    """

    async def fetch_with_access(
        self, credential_id: str, user_id: str, org_id: Optional[str]
    ) -> Optional[CredentialWithBlob]:
        """Fetch a credential (WITH encrypted blob) if the user has any of:
        owner, direct user share, or (in-org-context) org share. Returns
        ``None`` on no-access or missing — caller can't distinguish."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                self._FETCH_WITH_ACCESS_SQL, credential_id, user_id, org_id,
            )
        if not row:
            return None
        return CredentialWithBlob(
            id=str(row['id']),
            name=row['name'],
            credential_type=row['credential_type'],
            credential=row['credential'],
            metadata=row['metadata'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )

    # ------------------------------------------------------------------
    # update_credential
    # ------------------------------------------------------------------

    _HAS_EDIT_SQL = f"""
        SELECT 1
        FROM credentials c
        WHERE c.id = $1
          AND {credential_access_predicate(require_edit=True)}
    """

    async def has_edit_permission(
        self, credential_id: str, user_id: str, org_id: Optional[str]
    ) -> bool:
        """Edit-permission gate for update. Same three signals as
        ``fetch_with_access`` but requiring ``permission = 'edit'`` on
        shares. Delete is owner-only — see ``fetch_for_delete_as_owner``."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchval(
                self._HAS_EDIT_SQL, credential_id, user_id, org_id,
            )
        return row is not None

    async def update_metadata_or_fetch(
        self,
        credential_id: str,
        *,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[CredentialRow]:
        """UPDATE credentials with any provided (name, metadata) and RETURN
        the bare row. When neither is provided, SELECT the current row —
        the caller uses this fallback after a credential_data-only update
        went through the write choke point.

        The column names are interpolated into the SQL (they become part of
        SET clause), so they MUST be in ``_ALLOWED_UPDATE_COLS``.
        """
        updates: List[Tuple[str, Any]] = []
        if name is not None:
            updates.append(("name", name))
        if metadata is not None:
            updates.append(("metadata", metadata))

        for col, _ in updates:
            if col not in self._ALLOWED_UPDATE_COLS:
                raise ValueError(
                    f"column {col!r} not in allowlist "
                    f"{sorted(self._ALLOWED_UPDATE_COLS)}"
                )

        if not updates:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, name, credential_type, metadata, created_at, updated_at
                    FROM credentials WHERE id = $1
                    """,
                    credential_id,
                )
        else:
            params: List[Any] = [credential_id]
            set_parts: List[str] = []
            for i, (col, val) in enumerate(updates, start=2):
                set_parts.append(f"{col} = ${i}")
                params.append(val)
            set_parts.append("updated_at = NOW()")
            query = (
                f"UPDATE credentials SET {', '.join(set_parts)} "
                f"WHERE id = $1 "
                f"RETURNING id, name, credential_type, metadata, created_at, updated_at"
            )
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)

        if not row:
            return None
        return CredentialRow(
            id=str(row['id']),
            name=row['name'],
            credential_type=row['credential_type'],
            metadata=row['metadata'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )

    # ------------------------------------------------------------------
    # delete_credential
    # ------------------------------------------------------------------

    # Deliberately NOT credential_access_predicate: delete is owner-only.
    # An edit share grants use of a credential, never destruction of the
    # owner's row (which would also drop every other share of it).
    # Non-owners drop their own access via share:leave instead.
    _FETCH_FOR_DELETE_SQL = """
        SELECT c.credential_type, c.credential, c.organization_id
        FROM credentials c
        WHERE c.id = $1
          AND c.owner_id = $2
    """

    async def fetch_for_delete_as_owner(
        self, credential_id: str, user_id: str
    ) -> Optional[CredentialTypeAndBlob]:
        """Owner-gated fetch of the (credential_type, blob) pair — the two
        fields the handler needs to run provider-side revocation before
        DELETE. Returns ``None`` when the caller does not own the row."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                self._FETCH_FOR_DELETE_SQL, credential_id, user_id,
            )
        if not row:
            return None
        return CredentialTypeAndBlob(
            credential_type=row['credential_type'],
            credential=row['credential'],
            organization_id=str(row['organization_id']) if row['organization_id'] else None,
        )

    # Scans the three credentialIds locations the execution resolver reads
    # (see utils/credentials.collect_node_credential_uuids). Scoped to the
    # owner's + credential org's workflows — the only ones that can resolve
    # this credential at run time.
    _WORKFLOWS_REFERENCING_SQL = """
        SELECT DISTINCT w.id::text AS workflow_id, w.name
        FROM workflows w
        CROSS JOIN LATERAL jsonb_array_elements(w.workflow->'nodes') AS n
        WHERE w.deleted_at IS NULL
          AND (
              w.owner_id = $2
              OR ($3::uuid IS NOT NULL AND w.organization_id = $3::uuid)
          )
          AND (
              (jsonb_typeof(n->'data'->'credentialIds') = 'object' AND EXISTS (
                  SELECT 1 FROM jsonb_each_text(n->'data'->'credentialIds') kv
                  WHERE kv.value = $1))
              OR (jsonb_typeof(n->'data'->'config'->'credentialIds') = 'object' AND EXISTS (
                  SELECT 1 FROM jsonb_each_text(n->'data'->'config'->'credentialIds') kv
                  WHERE kv.value = $1))
              OR (jsonb_typeof(n->'config'->'credentialIds') = 'object' AND EXISTS (
                  SELECT 1 FROM jsonb_each_text(n->'config'->'credentialIds') kv
                  WHERE kv.value = $1))
          )
        ORDER BY w.name
    """

    async def list_workflows_referencing_credential(
        self, credential_id: str, owner_id: str, org_id: Optional[str]
    ) -> List[Dict[str, str]]:
        """Workflows whose nodes reference this credential id — the pre-delete
        usage warning surfaced to the owner."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                self._WORKFLOWS_REFERENCING_SQL, credential_id, owner_id, org_id,
            )
        return [
            {"workflow_id": r["workflow_id"], "workflow_name": r["name"] or "Untitled"}
            for r in rows
        ]

    _ACTIVE_WEBHOOK_NODES_SQL = """
        SELECT workflow_id::text AS workflow_id, node_id
        FROM webhooks
        WHERE registered_credential_id::text = $1
          AND is_active = true
    """

    async def list_active_webhook_nodes_for_credential(
        self, credential_id: str
    ) -> List[Dict[str, str]]:
        """Active webhook registrations keyed to this credential — the trigger
        nodes that must be deregistered BEFORE the credential row is deleted
        (teardown needs the credential to auth the provider call)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(self._ACTIVE_WEBHOOK_NODES_SQL, credential_id)
        return [
            {"workflow_id": r["workflow_id"], "node_id": r["node_id"]}
            for r in rows
        ]

    async def delete_credential_and_shares(self, credential_id: str) -> None:
        """Delete the credential row AND its ``resource_shares`` entries in
        one transaction. The ownership check ran earlier via
        ``fetch_for_delete_as_owner``; this method assumes the caller
        has already gated."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM credentials WHERE id = $1",
                    credential_id,
                )
                await conn.execute(
                    "DELETE FROM resource_shares "
                    "WHERE resource_type = 'credential' AND resource_id = $1",
                    credential_id,
                )

    # ------------------------------------------------------------------
    # credential_requests
    # ------------------------------------------------------------------

    _UPSERT_REQUEST_SQL = """
        INSERT INTO credential_requests (requester_id, target_email, credential_type, message)
        VALUES ($1, LOWER($2), $3, $4)
        ON CONFLICT (requester_id, target_email, credential_type)
        DO UPDATE SET
            message = EXCLUDED.message,
            token = encode(gen_random_bytes(32), 'hex'),
            expires_at = NOW() + INTERVAL '7 days',
            status = 'pending',
            provision_attempts = 0,
            fulfilled_at = NULL,
            credential_id = NULL
        RETURNING id, target_email, credential_type, message, status, token,
                  expires_at, created_at, fulfilled_at
    """

    async def upsert_credential_request(
        self,
        *,
        requester_id: str,
        target_email: str,
        credential_type: str,
        message: Optional[str],
    ) -> Optional[CredentialRequestRow]:
        """Insert-or-refresh a credential request. On conflict, rotates the
        token, resets expiry, and re-opens the request. Returns the shape
        the handler needs (including ``token``, needed to compose the
        outbound email)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                self._UPSERT_REQUEST_SQL,
                requester_id, target_email, credential_type, message,
            )
        if not row:
            return None
        return CredentialRequestRow(
            id=str(row['id']),
            target_email=row['target_email'],
            credential_type=row['credential_type'],
            message=row['message'],
            status=row['status'],
            credential_id=None,
            expires_at=row['expires_at'],
            created_at=row['created_at'],
            fulfilled_at=row['fulfilled_at'],
            token=row['token'],
        )

    async def list_credential_requests(
        self, requester_id: str
    ) -> List[CredentialRequestRow]:
        """Outgoing credential requests for the current user."""
        sql = """
            SELECT id, target_email, credential_type, message, status,
                   credential_id, expires_at, created_at, fulfilled_at
            FROM credential_requests
            WHERE requester_id = $1
            ORDER BY created_at DESC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, requester_id)
        return [
            CredentialRequestRow(
                id=str(r['id']),
                target_email=r['target_email'],
                credential_type=r['credential_type'],
                message=r['message'],
                status=r['status'],
                credential_id=str(r['credential_id']) if r['credential_id'] else None,
                expires_at=r['expires_at'],
                created_at=r['created_at'],
                fulfilled_at=r['fulfilled_at'],
                token=None,
            )
            for r in rows
        ]

    async def cancel_credential_request(
        self, request_id: str, requester_id: str
    ) -> bool:
        """Cancel a pending request. Returns True iff a row moved out of
        'pending' (i.e. the request existed and belonged to the caller)."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE credential_requests
                SET status = 'cancelled'
                WHERE id = $1 AND requester_id = $2 AND status = 'pending'
                """,
                request_id, requester_id,
            )
        # asyncpg returns the string 'UPDATE N' — the same non-zero check
        # the handler used inline.
        return result != 'UPDATE 0'


async def create_credential_with_limit_check(
    conn, user_id: str, user_tier: str, credential_type: str,
    credential_name: str, encrypted_data: str, metadata: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Check the plan's credential limit, resolve org context, and insert a
    new credential. Shared by all OAuth handlers and the generic credential
    handler to avoid duplicating the limit-check + org-context + INSERT
    pattern.

    Returns (credential_row_dict, None) on success or (None, error_message)
    on limit hit.
    """
    # The one billing edge on this path; lazy so the metering implementation
    # stays swappable behind it.
    from billing.plan_limits import check_credential_limit

    method = 'oauth' if 'oauth' in credential_type.lower() else 'api_key'

    can_create, limit_error = await check_credential_limit(conn, user_id, user_tier, credential_type)
    if not can_create:
        log_activity_background(Events.CREDENTIAL_CONNECTION_FAILED, user_id, {
            "credential_type": credential_type,
            "method": method,
            "reason": "limit_exceeded",
            "tier": user_tier,
        })
        return None, limit_error

    org_row = await conn.fetchrow(PRIMARY_ORG_SQL, user_id)
    org_id = str(org_row['organization_id']) if org_row else None

    row = await conn.fetchrow("""
        INSERT INTO credentials (owner_id, organization_id, name, credential_type, credential, metadata, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        RETURNING id, name, credential_type, metadata, created_at, updated_at
    """, user_id, org_id, credential_name, credential_type, encrypted_data, metadata)

    if not row:
        log_activity_background(Events.CREDENTIAL_CONNECTION_FAILED, user_id, {
            "credential_type": credential_type,
            "method": method,
            "reason": "db_insert_failed",
        })
        return None, "Failed to store credential"

    log_activity_background(Events.CREDENTIAL_CONNECTED, user_id, {
        "credential_type": credential_type,
        "method": method,
    })
    return dict(row), None
