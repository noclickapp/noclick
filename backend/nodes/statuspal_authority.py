"""StatusPal saved credential snapshots using staging's canonical access predicate."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from repositories.credentials import credential_access_predicate


@dataclass(frozen=True)
class StatusPalCredentialRow:
    credential_type: str
    owner_id: str
    token_version: int
    updated_at: datetime
    approval_revision: int
    revoked_at: datetime | None
    credential: Any = field(repr=False)


class StatusPalCredentialsRepo:
    def __init__(self, pool):
        self.pool = pool

    async def fetch_validation_authority(self, credential_id, user_id, org_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT c.credential_type,c.owner_id,c.token_version,c.updated_at,"
                f"c.approval_revision,c.revoked_at,c.credential FROM credentials c "
                f"WHERE c.id=$1 AND {credential_access_predicate()}",
                credential_id, user_id, org_id,
            )
        return StatusPalCredentialRow(
            credential_type=row["credential_type"], owner_id=str(row["owner_id"]),
            token_version=row["token_version"], updated_at=row["updated_at"],
            approval_revision=row["approval_revision"], revoked_at=row["revoked_at"],
            credential=row["credential"],
        ) if row else None
