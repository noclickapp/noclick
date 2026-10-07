"""Current credential authority and conditional OAuth maintenance writes.

SQL composes the canonical credential predicate. Refresh writes retain revoke
state; reconnect continues using its existing separate authoritative writer.
"""
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


class OAuthRefreshAuthorityRepo:
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
        return row, organization_id

    @staticmethod
    def _arguments(anchor):
        return [anchor.credential_id, anchor.principal_id, anchor.organization_id,
                anchor.caller_id, anchor.current_organization, anchor.workflow_id,
                anchor.owner_id, anchor.credential_type, anchor.token_version]

    async def persist(self, anchor, encrypted_data, metadata_updates):
        async with self.pool.acquire() as conn:
            tag = await conn.execute(f"""
                UPDATE credentials c
                SET credential = $10,
                    metadata = COALESCE(c.metadata, '{{}}'::jsonb) || $11::jsonb,
                    updated_at = NOW()
                WHERE c.id = $1::uuid AND {_authority_guard()}
                  AND c.owner_id = $7::uuid AND c.credential_type = $8
                  AND c.token_version = $9 AND c.revoked_at IS NULL
            """, *self._arguments(anchor), encrypted_data, metadata_updates or {})
        return int(tag.rsplit(" ", 1)[-1])

    @staticmethod
    async def mark_revoked(conn, anchor, reason):
        return await conn.execute(f"""
            UPDATE credentials c
            SET revoked_at = NOW(), revoked_reason = $10
            WHERE c.id = $1::uuid AND {_authority_guard()}
              AND c.owner_id = $7::uuid AND c.credential_type = $8
              AND c.token_version = $9 AND c.revoked_at IS NULL
        """, *OAuthRefreshAuthorityRepo._arguments(anchor), reason)
