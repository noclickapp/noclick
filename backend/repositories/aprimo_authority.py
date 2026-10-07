"""Aprimo current-row reads, using the canonical credential access predicate."""

from repositories.credentials import credential_access_predicate


async def current_aprimo_row(conn, credential_id, actor_id, organization_id):
    row = await conn.fetchrow(
        f"""SELECT c.id, c.owner_id, c.organization_id, c.credential_type,
                   c.credential, c.token_version, c.updated_at, c.metadata, c.revoked_at
            FROM credentials c WHERE c.id = $1 AND {credential_access_predicate()}""",
        credential_id, actor_id, organization_id,
    )
    return dict(row) if row else None
