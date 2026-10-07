"""Read current Docspell rows through the canonical credential access policy.

The workflow clause rechecks an explicitly authorized current owner fallback.
"""
from repositories.credentials import credential_access_predicate


async def fetch_snapshot(pool, credential_id, user_id, organization_id=None, *, workflow_id=None):
    workflow_guard = "" if workflow_id is None else """
      AND EXISTS (SELECT 1 FROM workflows w
          JOIN workflow_authorized_credentials a ON a.workflow_id = w.id
          WHERE w.id = $4 AND w.owner_id = $2 AND a.credential_id = c.id)
    """
    args = [credential_id, user_id, organization_id]
    if workflow_id is not None:
        args.append(workflow_id)
    async with pool.acquire() as conn:
        return await conn.fetchrow(f"""
          SELECT c.credential, c.credential_type, c.owner_id, c.token_version, c.revoked_at
          FROM credentials c WHERE c.id = $1
          AND {credential_access_predicate()} {workflow_guard}
        """, *args)
