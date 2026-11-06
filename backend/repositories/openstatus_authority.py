"""Read-only current credential authority for OpenStatus.

SQL composes the canonical credential predicate. Only this integration uses this adapter; it never persists supplied API keys.
"""
from datetime import datetime
from repositories.credentials import credential_access_predicate
from repositories.organization import OrgRepo, PRIMARY_ORG_SQL


def _authority_guard():
    # $2 is the currently resolved principal; $4 is the actual runner. A
    # fallback principal must STILL own the workflow and its positive grant.
    primary_org = PRIMARY_ORG_SQL.replace("$1", "$4::uuid")
    return f"""
        {credential_access_predicate()}
        AND (NOT $5::boolean OR $3::uuid IS NOT DISTINCT FROM ({primary_org}))
        AND ($2::uuid = $4::uuid OR (
            $6::uuid IS NOT NULL AND EXISTS (
                SELECT 1 FROM workflows w
                JOIN workflow_authorized_credentials a ON a.workflow_id = w.id
                WHERE w.id = $6::uuid AND w.owner_id = $2::uuid
                  AND a.credential_id = c.id
            )
        ))
    """


class OpenStatusAuthorityRepo:
    def __init__(self, pool):
        self.pool = pool

    async def load(self, credential_id, principal_id, organization_id, *,
                   caller_id, current_organization, workflow_id):
        async with self.pool.acquire() as conn:
            if current_organization:
                organization_id = await OrgRepo(self.pool).get_primary_org_id(conn, caller_id)
            row = await conn.fetchrow(f"""
                SELECT c.credential, c.owner_id, c.credential_type, c.token_version,
                       c.updated_at, c.revoked_at
                FROM credentials c
                WHERE c.id = $1::uuid AND {_authority_guard()}
            """, credential_id, principal_id, organization_id, caller_id,
                current_organization, workflow_id)
        if row is not None and (not isinstance(row["updated_at"], datetime) or row["updated_at"].tzinfo is None):
            raise ValueError("OpenStatus saved credential timestamp is invalid")
        return row, organization_id
