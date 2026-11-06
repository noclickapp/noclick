"""Read current Bytescale rows through the canonical credential access policy.

The workflow clause rechecks an explicitly authorized current owner fallback.
"""
from repositories.credentials import credential_access_predicate
from repositories.organization import PRIMARY_ORG_SQL


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
        sql = f"""
          SELECT c.credential, c.credential_type, c.owner_id, c.token_version, c.revoked_at
          FROM credentials c WHERE c.id = $1
          AND {credential_access_predicate()} {workflow_guard}
        """
        row = await conn.fetchrow(sql, *args)
        # Staging freshening hooks supply the caller but no organization context.
        # Recheck the caller’s current server-side org through the same access policy.
        if row is None and organization_id is None and workflow_id is None:
            org = await conn.fetchrow(PRIMARY_ORG_SQL, user_id)
            if org is not None:
                args[2] = str(org["organization_id"])
                row = await conn.fetchrow(sql, *args)
        return row
