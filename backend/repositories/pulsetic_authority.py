"""Current Pulsetic row access using the existing resource-share predicate."""
from uuid import UUID

from repositories.credentials import credential_access_predicate


async def current_pulsetic_row(conn, credential_id, actor_id, org_id):
    return await conn.fetchrow(
        f"SELECT c.id, c.owner_id, c.organization_id, c.credential_type, "
        f"c.credential, c.revoked_at, c.token_version, c.updated_at "
        f"FROM credentials c WHERE c.id=$1::uuid AND {credential_access_predicate()}",
        UUID(str(credential_id)), UUID(str(actor_id)), UUID(str(org_id)) if org_id else None,
    )
