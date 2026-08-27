"""
Utility functions for managing credentials programmatically.

These utilities provide direct access to credential operations for internal use,
bypassing the WebSocket routing system.
"""

import json
import logging
import uuid as _uuid
from typing import Dict, Any, List, Optional
from repositories.credentials import credential_access_predicate
from repositories.workflow import WorkflowRepo
from utils.database_pool import get_native_pool
from utils.encryption import get_encryption

logger = logging.getLogger(__name__)


def _is_credential_uuid(value: Any) -> bool:
    """A hardcoded credential reference is a real UUID — not an empty string, a
    `{{vars.X}}` reference, or the `credential_type` metadata marker."""
    if not isinstance(value, str) or not value or "{{" in value:
        return False
    try:
        _uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def credential_metadata(row: Any) -> Dict[str, Any]:
    """The metadata dict of a credentials row, tolerating pools without the
    jsonb codec (which return jsonb as its JSON text — e.g. daily_maintenance)."""
    meta = (row.get("metadata") if hasattr(row, "get") else getattr(row, "metadata", None)) or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (ValueError, TypeError):
            return {}
    return meta if isinstance(meta, dict) else {}


def collect_node_credential_uuids(workflow_blob: Any) -> set:
    """Collect the credential UUIDs hardcoded onto a workflow's nodes.

    Reads the three locations the execution resolver understands —
    `node.data.credentialIds`, `node.data.config.credentialIds`, and the legacy
    flat `node.config.credentialIds` — each a `{credential_type: value}` map.
    Skips empties, `{{vars.X}}` refs, and the `credential_type` metadata key."""
    if isinstance(workflow_blob, str):
        try:
            workflow_blob = json.loads(workflow_blob)
        except (ValueError, TypeError):
            return set()
    if not isinstance(workflow_blob, dict):
        return set()

    out: set = set()
    for node in workflow_blob.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = data.get("config") if isinstance(data.get("config"), dict) else {}
        flat_config = node.get("config") if isinstance(node.get("config"), dict) else {}
        for cred_map in (data.get("credentialIds"), config.get("credentialIds"), flat_config.get("credentialIds")):
            if not isinstance(cred_map, dict):
                continue
            for key, value in cred_map.items():
                if key == "credential_type":
                    continue
                if _is_credential_uuid(value):
                    out.add(value)
    return out


async def get_credential(credential_id: str, user_id: str, pool=None, org_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Retrieve and decrypt a credential by ID for a specific user.

    This utility provides programmatic access to credentials for internal use.
    It fetches the encrypted credential from the database, verifies ownership,
    and returns the decrypted data.

    Args:
        credential_id: UUID of the credential to retrieve
        user_id: UUID of the user who owns the credential
        pool: Optional database pool (for testing). If None, uses global pool.
        org_id: Optional organization context. If provided, org-shared credentials
                are only accessible if shared with this specific org. If None,
                only owner and direct user shares are accessible.

    Returns:
        Dictionary containing decrypted credential data if found and accessible,
        None if credential doesn't exist or user doesn't have access

    Example:
        >>> cred_data = await get_credential("cred-uuid-123", "user-uuid-456")
        >>> if cred_data:
        >>>     api_key = cred_data.get("api_key")
    """
    try:
        if pool is None:
            pool = get_native_pool()

        async with pool.acquire() as conn:
            # Fetch credential if the user has access (canonical predicate:
            # owner / direct user-share / matching org-share).
            row = await conn.fetchrow(f"""
                SELECT c.credential, c.revoked_at
                FROM credentials c
                WHERE c.id = $1
                  AND {credential_access_predicate()}
            """, credential_id, user_id, org_id)

            if not row:
                logger.warning(
                    f"[CredentialsUtil] Credential {credential_id} not found "
                    f"or user {user_id} doesn't have access"
                )
                return None

            if row['revoked_at'] is not None:
                # Auto-revoked by oauth_refresh.py after consecutive provider_4xx
                # failures with the same dead refresh token. Reconnecting (via the
                # OAuth exchange handler) clears the flag.
                logger.warning(
                    f"[CredentialsUtil] Credential {credential_id} is revoked "
                    f"(revoked_at={row['revoked_at']}); refusing to load"
                )
                return None

            # Decrypt the credential data
            encryption = get_encryption()
            try:
                credential_data = encryption.decrypt_credential(row['credential'])
                logger.info(f"[CredentialsUtil] Retrieved credential {credential_id} for user {user_id}")
                return credential_data
            except Exception as e:
                logger.error(f"[CredentialsUtil] Failed to decrypt credential {credential_id}: {e}")
                return None

    except Exception as e:
        logger.error(f"[CredentialsUtil] Error retrieving credential: {e}", exc_info=True)
        return None


# Row-level columns that load_credential injects into the decrypted dict for
# the refresh path. They must never be encrypted into the blob, or a later
# load would shadow the live column with a stale copy.
_NON_BLOB_KEYS = ("token_version", "updated_at")


def strip_non_blob_keys(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of *data* without row-level (non-secret) bookkeeping keys."""
    return {k: v for k, v in data.items() if k not in _NON_BLOB_KEYS}


async def update_credential_data_detailed(
    credential_id: str,
    user_id: str,
    new_data: Dict[str, Any],
    metadata_updates: Optional[Dict[str, Any]] = None,
    pool=None,
    expected_token_version: Optional[int] = None,
    credential_name: Optional[str] = None,
) -> tuple[int, Optional[str]]:
    """Persist a credential update and return ``(rows_affected, error_class)``.

    The detailed shape exists so the OAuth refresh audit can distinguish a
    zero-rows persist (credential deleted mid-refresh — F39 / F17) from a
    DB exception (schema drift, txn abort — F37 / F17), both of which the
    legacy ``update_credential_data`` collapses to ``False``.

    Semantics (system-level token-refresh persist):
    - Keyed by ``credential_id`` only — NOT filtered by owner. Access is
      verified when the credential is loaded; a refreshed rotating token MUST
      be saved regardless of which user ran the workflow, since failing to
      persist a consumed single-use token bricks the owner's copy.
    - ``user_id`` is logged only.
    - Merges ``new_data`` into the existing encrypted blob; metadata is
      merged as JSONB ``||``.
    - ``credential_name`` optionally refreshes the display name alongside a
      new authoritative OAuth grant.
    - ``expected_token_version`` makes the write a compare-and-swap: it only
      lands if the row's ``token_version`` still matches the value read with
      the snapshot ``new_data`` was derived from (a DB trigger bumps the
      version on every blob change, including raw-SQL writers). A stale
      snapshot then loses with ``rows_affected == 0`` instead of silently
      reverting a concurrent writer's tokens — re-read and re-apply to retry.
      ``None`` keeps the legacy unconditional write (correct for fresh OAuth
      installs, where the new grant is authoritative).

    Returns:
        ``(rows_affected, error_class)`` where ``error_class`` is the
        exception class name on failure (else ``None``). ``rows_affected==0``
        with ``error_class is None`` means the row was not found — or, with
        ``expected_token_version`` set, that the CAS guard failed.
    """
    try:
        if pool is None:
            pool = get_native_pool()

        encryption = get_encryption()
        encrypted_data = encryption.encrypt_credential(strip_non_blob_keys(new_data))

        async with pool.acquire() as conn:
            # Clearing revoked_at on every successful write is intentional: a
            # successful refresh OR a fresh re-authorization means the credential
            # is good again, so the auto-revoke flag set by oauth_refresh.py
            # should clear automatically.
            if metadata_updates:
                version_guard = (
                    "" if expected_token_version is None else "AND token_version = $5"
                )
                args = [
                    encrypted_data,
                    metadata_updates,
                    credential_name,
                    credential_id,
                ]
                if expected_token_version is not None:
                    args.append(expected_token_version)
                result = await conn.execute(f"""
                    UPDATE credentials
                    SET credential = $1,
                        metadata = metadata || $2::jsonb,
                        name = COALESCE($3, name),
                        updated_at = NOW(),
                        revoked_at = NULL,
                        revoked_reason = NULL
                    WHERE id = $4 {version_guard}
                """, *args)
            else:
                version_guard = (
                    "" if expected_token_version is None else "AND token_version = $4"
                )
                args = [encrypted_data, credential_name, credential_id]
                if expected_token_version is not None:
                    args.append(expected_token_version)
                result = await conn.execute(f"""
                    UPDATE credentials
                    SET credential = $1,
                        name = COALESCE($2, name),
                        updated_at = NOW(),
                        revoked_at = NULL,
                        revoked_reason = NULL
                    WHERE id = $3 {version_guard}
                """, *args)

            # asyncpg returns 'UPDATE N' on success — parse the count.
            try:
                rows_affected = int(result.rsplit(" ", 1)[-1]) if isinstance(result, str) else 0
            except (ValueError, AttributeError):
                rows_affected = 0
            if rows_affected > 0:
                logger.info(f"[CredentialsUtil] Updated credential {credential_id} (refresh by user {user_id})")
            else:
                logger.warning(
                    f"[CredentialsUtil] Credential {credential_id} not found "
                    f"(refresh by user {user_id})"
                )
            return rows_affected, None

    except Exception as e:
        logger.error(f"[CredentialsUtil] Error updating credential: {e}", exc_info=True)
        return 0, e.__class__.__name__


async def update_credential_data(
    credential_id: str,
    user_id: str,
    new_data: Dict[str, Any],
    metadata_updates: Optional[Dict[str, Any]] = None,
    pool=None,
    credential_name: Optional[str] = None,
) -> bool:
    """Backwards-compatible bool wrapper around ``update_credential_data_detailed``.

    Returns ``True`` iff a row was actually updated. New callers in the OAuth
    refresh path should prefer the detailed variant so the audit can
    distinguish zero-rows from a DB exception.
    """
    rows_affected, _ = await update_credential_data_detailed(
        credential_id=credential_id,
        user_id=user_id,
        new_data=new_data,
        metadata_updates=metadata_updates,
        pool=pool,
        credential_name=credential_name,
    )
    return rows_affected > 0


async def list_credentials(user_id: str, pool=None, org_id: Optional[str] = None) -> list:
    """
    List all credentials for a user (metadata only, no decrypted data).

    Args:
        user_id: UUID of the user
        pool: Optional database pool (for testing). If None, uses global pool.
        org_id: Optional organization context. If provided, org-shared credentials
                are only listed if shared with this specific org. If None,
                only owner and direct user shares are listed.

    Returns:
        List of dictionaries containing credential metadata (id, name, type, etc.)
        Empty list if no credentials found or on error
    """
    try:
        if pool is None:
            pool = get_native_pool()

        async with pool.acquire() as conn:
            # Fetch all credentials the user can access:
            # 1. Credentials they own
            # 2. Credentials shared with them directly
            # 3. Credentials shared with their current org (only when org_id provided)
            rows = await conn.fetch("""
                SELECT DISTINCT ON (c.id)
                    c.id, c.name, c.credential_type, c.metadata, c.created_at, c.updated_at,
                    c.owner_id,
                    CASE WHEN c.owner_id = $1 THEN 0 ELSE 1 END as sort_order
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
                WHERE
                    c.owner_id = $1
                    OR us.id IS NOT NULL
                    OR ($2::uuid IS NOT NULL AND os.id IS NOT NULL)
                ORDER BY c.id, sort_order, c.created_at DESC
            """, user_id, org_id)

            # Sort the results by sort_order and created_at
            rows = sorted(rows, key=lambda r: (r['sort_order'], -r['created_at'].timestamp()))

            credentials = []
            for row in rows:
                credentials.append({
                    'id': str(row['id']),
                    'name': row['name'],
                    'credential_type': row['credential_type'],
                    'metadata': row['metadata'],
                    'created_at': row['created_at'].isoformat(),
                    'updated_at': row['updated_at'].isoformat()
                })

            logger.info(f"[CredentialsUtil] Listed {len(credentials)} credentials for user {user_id}")
            return credentials

    except Exception as e:
        logger.error(f"[CredentialsUtil] Error listing credentials: {e}", exc_info=True)
        return []


def extract_credential_ids(config: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the credential-id mapping from a node config blob, across every
    known payload variant. SINGLE DEFINITION — the workflow execution handler
    and the agent tool-provider path must accept the same shapes, or a config
    that runs fine normally silently loses its credential in provider mode.
    """
    # Preferred frontend shape
    if isinstance(config.get('credentialIds'), dict):
        return config.get('credentialIds', {})
    # Snake_case variant
    if isinstance(config.get('credential_ids'), dict):
        return config.get('credential_ids', {})
    # Single-id variants
    for key in ('credential_id', 'credentialId'):
        val = config.get(key)
        if isinstance(val, str) and val.strip():
            return {'default': val}
    # Legacy/alternate location: credentials object containing an ID
    creds_obj = config.get('credentials')
    if isinstance(creds_obj, dict):
        for key in ('credential_id', 'credentialId', 'id'):
            val = creds_obj.get(key)
            if isinstance(val, str) and val.strip():
                return {'default': val}
    return {}


# Credential types that ride a node's credentialIds map WITHOUT authenticating the
# node itself. They must stay in the map — that is what the delete-impact scan and
# authorize_credentials_for_workflow read — but they can never be the node's primary
# credential. Every "which credential does this node use / does it have one?"
# predicate must skip them: pick_credential_id (else insertion order decides whether
# an agent resolves its model key or its env bundle) and workflow_ops
# .node_has_credential (else an agent with env vars but no model key looks
# credentialed and the builder stops asking the user to connect one).
NON_PRIMARY_CREDENTIAL_TYPES = frozenset({'agent_env'})


def pick_credential_id(credential_ids: Dict[str, Any]) -> Optional[str]:
    """First usable credential id from an extracted mapping. credentialIds may
    carry multiple keys for alternate auth types where unselected entries are
    empty strings; skips the credential_type metadata key, non-primary types
    (see NON_PRIMARY_CREDENTIAL_TYPES), empties, and unresolved {{...}}
    variable references."""
    return next(
        (
            v for k, v in credential_ids.items()
            if k != 'credential_type'
            and k not in NON_PRIMARY_CREDENTIAL_TYPES
            and isinstance(v, str)
            and v.strip() != ''
            and '{{' not in v
        ),
        None,
    )


async def resolve_credential_with_owner_fallback(
    credential_id: str,
    user_id: str,
    pool,
    *,
    org_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    get_owner_id=None,
) -> Optional[Dict[str, Any]]:
    """THE owner-fallback credential resolution policy — single definition.

    Try the RUNNER first (preserving their own / explicitly-shared
    credentials), then fall back to the workflow OWNER — but ONLY for
    credentials the owner authorized for this workflow
    (workflow_authorized_credentials, fail-closed): without the gate a
    collaborator could point a node at any owner-owned credential UUID and
    exfiltrate its secret.

    `get_owner_id` optionally overrides the owner lookup (the execution
    handler injects its cached resolver); defaults to get_workflow_owner_id.

    Returns the decrypted credential dict, or None if unresolvable.
    """
    credential_data = await get_credential(credential_id, user_id, pool, org_id)
    if not credential_data and workflow_id:
        if get_owner_id is not None:
            owner_id = await get_owner_id(workflow_id)
        else:
            owner_id = await get_workflow_owner_id(pool, workflow_id)
        if (
            owner_id
            and owner_id != user_id
            and await is_credential_authorized_for_workflow(pool, workflow_id, credential_id)
        ):
            credential_data = await get_credential(credential_id, owner_id, pool, org_id)
    return credential_data


async def get_credential_name(pool, credential_id: str) -> Optional[str]:
    """Display name of a credential — NO secret, NO access grant (same class of
    exposure as the credential:display_info handler). Used to tag agent tool
    descriptions so the model can tell same-type providers apart."""
    try:
        cred_uuid = credential_id if not isinstance(credential_id, str) else _uuid.UUID(credential_id)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT name FROM credentials WHERE id = $1 AND revoked_at IS NULL",
                cred_uuid,
            )
        return row["name"] if row else None
    except Exception as e:
        logger.warning(f"[CredentialsUtil] Name lookup failed for {credential_id}: {e}")
        return None


async def get_workflow_owner_id(pool, workflow_id: str) -> Optional[str]:
    """Resolve a workflow's owner id (uncached). Returns None on error or not-found.

    Used by the run-as-owner execution fallback so a collaborator can run a shared
    flow with the owner's credentials. Callers that resolve frequently may cache the
    (immutable) result.
    """
    try:
        # include_deleted: run-as-owner resolution (trigger runs, cleanup) must
        # still resolve a trashed workflow's owner.
        return await WorkflowRepo(pool).get_owner_id(workflow_id, include_deleted=True)
    except Exception as e:
        logger.warning(f"[CredentialsUtil] Could not resolve owner for workflow {workflow_id}: {e}")
        return None


# Batched "credential ids this user may use" — the canonical access predicate
# plus a revoked_at filter (revocation is checked here, not in the fragment).
# Selects the type too so callers can both filter accessibility AND re-key by
# the credential's ACTUAL type in one round-trip.
_ACCESSIBLE_CREDENTIALS_SQL = f"""
    SELECT c.id, c.credential_type FROM credentials c
    WHERE c.id = ANY($1::uuid[])
      AND c.revoked_at IS NULL
      AND {credential_access_predicate()}
"""


async def resolve_accessible_credential_types(
    credential_ids, user_id: str, pool=None, org_id: Optional[str] = None,
) -> Dict[str, str]:
    """Map each accessible id in ``credential_ids`` to its ACTUAL ``credential_type``.

    Same access semantics as :func:`filter_accessible_credential_ids` (owner /
    direct user-share / matching org-share, not revoked) — inaccessible, revoked,
    bogus, and malformed (non-UUID) ids are simply absent from the result, so this
    doubles as the accessibility filter. Returns ``{credential_id: credential_type}``
    with the ids in their ORIGINAL string form. No decryption (unlike
    :func:`get_credential`); one batched query (unlike :func:`list_credentials`).

    AI write paths use this to file a ``<set_credentials>`` id under the slot the
    credential ACTUALLY belongs to (e.g. a ``slack_bot_token`` under
    ``slack_bot_token``, not the node schema's first type ``slack_oauth``). The
    frontend keys ``credentialIds`` by ``credential_type``, so the real type is
    what makes the credential show as selected.
    """
    norm_to_orig: Dict[str, Any] = {}
    uuids = []
    for c in (credential_ids or []):
        if c and _is_credential_uuid(str(c)):
            u = _uuid.UUID(str(c))
            norm_to_orig[str(u)] = c
            uuids.append(u)
    if not uuids:
        return {}
    if pool is None:
        pool = get_native_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_ACCESSIBLE_CREDENTIALS_SQL, uuids, user_id, org_id)
    return {norm_to_orig[str(r['id'])]: r['credential_type'] for r in rows}


async def filter_accessible_credential_ids(
    credential_ids, user_id: str, pool=None, org_id: Optional[str] = None,
) -> set:
    """Return the subset of ``credential_ids`` that EXIST and are accessible to
    ``user_id`` (owner / direct user-share / org-share) and are not revoked.

    AI write paths (the agentic builder and the external MCP) take credential ids
    straight from the model or a stale FE picker and place them via
    ``<set_credentials>``. A bogus or inaccessible id would FK-violate
    ``workflow_authorized_credentials`` in
    :func:`authorize_credentials_for_workflow` (crashing the build) or get
    silently persisted into node config to fail later with ``invalid_auth`` — so
    both chokepoints validate against this first and surface a graceful
    "pick another" error. Mirrors the access predicate in :func:`get_credential`,
    batched and without decrypting. Malformed (non-UUID) ids are never accessible.

    Returns the valid ids in their ORIGINAL string form (so callers can compare
    against what the model emitted regardless of UUID casing). Thin wrapper over
    :func:`resolve_accessible_credential_types` so the access predicate lives once.
    """
    return set(await resolve_accessible_credential_types(
        credential_ids, user_id, pool=pool, org_id=org_id,
    ))


async def authorize_credentials_for_workflow(conn, workflow_id: str, authorized_by: str, credential_ids) -> None:
    """Record that the workflow OWNER authorized `credential_ids` for run-as-owner
    resolution on this workflow (workflow_authorized_credentials). Call this ONLY for
    owner-attributed credential placements — the OWNER's explicit UI pick, or an
    owner-driven server path (SDK set_node_config, external MCP set_credentials, the
    internal builder). Do NOT call it from the collaborative frontend autosave: that
    blob can contain credentialIds a collaborator injected via the presence channel,
    which would then ride into the authorized set on the owner's save. Idempotent.

    `conn` is an acquired connection; `credential_ids` is any iterable of UUID strings.
    """
    ids = [_uuid.UUID(c) if isinstance(c, str) else c
           for c in (credential_ids or []) if c and _is_credential_uuid(str(c))]
    if not ids:
        return
    wf_uuid = workflow_id if not isinstance(workflow_id, str) else _uuid.UUID(workflow_id)
    by_uuid = authorized_by if not isinstance(authorized_by, str) else _uuid.UUID(authorized_by)
    await conn.execute(
        """
        INSERT INTO workflow_authorized_credentials (workflow_id, credential_id, authorized_by)
        SELECT $1::uuid, c, $2::uuid FROM unnest($3::uuid[]) AS c
        ON CONFLICT (workflow_id, credential_id) DO NOTHING
        """,
        wf_uuid, by_uuid, ids,
    )


async def is_credential_authorized_for_workflow(pool, workflow_id: str, credential_id: str) -> bool:
    """Whether `credential_id` is in the workflow's owner-authorized credential set
    (workflow_authorized_credentials) — i.e. the OWNER placed it on the flow.

    Gates the run-as-owner fallback so a collaborator cannot point a node at an
    arbitrary owner-owned credential UUID to exfiltrate it. Fail-CLOSED (returns
    False) on any error — we never resolve as owner without a positive check.
    """
    try:
        wf_uuid = workflow_id if not isinstance(workflow_id, str) else _uuid.UUID(workflow_id)
        cred_uuid = credential_id if not isinstance(credential_id, str) else _uuid.UUID(credential_id)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM workflow_authorized_credentials WHERE workflow_id = $1 AND credential_id = $2",
                wf_uuid,
                cred_uuid,
            )
        return row is not None
    except Exception as e:
        logger.warning(
            f"[CredentialsUtil] Authorization check failed for credential {credential_id} "
            f"on workflow {workflow_id}: {e}"
        )
        return False
