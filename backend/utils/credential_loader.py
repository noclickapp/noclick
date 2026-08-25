"""Shared credential resolution for node field-loading.

``WorkflowNode.load_field_value`` runs outside workflow execution (when a
config UI is opened), so it has no parsed credential model — only a
``credential_ids`` map. This module resolves a credential id to its decrypted
secret dict, honoring the same access rules as workflow execution: the caller
must own the credential, or have it shared with them directly, or via their
current organization context.
"""

import logging
from typing import Any, Dict, Optional

from repositories.credentials import credential_access_predicate

logger = logging.getLogger(__name__)

_LOAD_CREDENTIAL_SQL = f"""
    SELECT c.credential, c.revoked_at, c.token_version, c.updated_at, c.credential_type
    FROM credentials c
    WHERE c.id = $1 AND {credential_access_predicate()}
"""


async def load_credential(
    pool, user_id: str, credential_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Fetch and decrypt a credential the user is allowed to use.

    Returns the decrypted credential dict, or ``None`` if no credential id was
    given or it is not accessible to *user_id*.
    """
    if not credential_id:
        return None

    from utils.encryption import get_encryption
    from wss.handlers.workflow_handler import get_user_org_context

    if pool is None:
        from utils.database_pool import get_native_pool

        pool = get_native_pool()
    try:
        async with pool.acquire() as conn:
            org_id = await get_user_org_context(conn, user_id)
            row = await conn.fetchrow(
                _LOAD_CREDENTIAL_SQL, credential_id, user_id, org_id,
            )
    except Exception as e:
        logger.error(f"[credential_loader] Error fetching credential {credential_id}: {e}")
        return None

    if not row:
        return None
    if row["revoked_at"] is not None:
        # Credential was auto-marked bricked by oauth_refresh.py after consecutive
        # provider_4xx failures with the same dead refresh token. Refusing to load
        # short-circuits the retry storm — user must reconnect (which clears the
        # flag via update_credential_data).
        logger.warning(
            "[credential_loader] credential %s is revoked (revoked_at=%s); refusing to load",
            credential_id, row["revoked_at"],
        )
        return None
    data = get_encryption().decrypt_credential(row["credential"])
    # Row-level (non-secret) fields the OAuth refresh path needs: token_version
    # is the optimistic-concurrency guard for CAS persists, updated_at feeds the
    # audit's read-your-writes lag detectors. Both are stripped from the dict
    # before any blob write (see utils.credentials._NON_BLOB_KEYS).
    data["token_version"] = row["token_version"]
    if row["updated_at"] is not None:
        data["updated_at"] = row["updated_at"].isoformat()
    # Inject credential_type so trigger-path code that type-checks credentials
    # (e.g. _bot_auth_header_from_credential) works consistently whether
    # credentials arrive via execution or load_field_value.
    credential_type = row.get("credential_type")
    if credential_type is not None:
        data["credential_type"] = credential_type
    return data
