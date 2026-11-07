"""Read current stored authority for Proposify already-issued tokens."""
from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID

from repositories.credentials import credential_access_predicate
from repositories.organization import OrgRepo, PRIMARY_ORG_SQL


CURRENT_ORGANIZATION = object()


@dataclass(frozen=True)
class CredentialAuthority:
    credential_id: str
    caller_id: str
    principal_id: str
    organization_id: str | None
    current_organization: bool
    workflow_id: str | None
    owner_id: str
    credential_type: str
    token_version: int


class ProposifyCredentialsTableStore:
    def __init__(self, pool, user_id, credential_id, *, credential_type,
                 validate, organization_id=CURRENT_ORGANIZATION, workflow_id=None):
        self.pool = pool
        self.user_id = str(UUID(str(user_id)))
        self.credential_id = str(UUID(str(credential_id)))
        self.credential_type = credential_type
        self.validate = validate
        self.organization_id = organization_id
        self.workflow_id = str(UUID(str(workflow_id))) if workflow_id else None
        self.current = None

    def _repo(self):
        if self.pool is None:
            from utils.database_pool import get_native_pool
            self.pool = get_native_pool()
        return ProposifyAuthorityRepo(self.pool)

    def _validated(self, data):
        try:
            shaped = self.validate(data)
        except Exception:
            # Model and provider-validation input details can contain tokens.
            raise ValueError("Proposify credential grant shape or binding is invalid.") from None
        if not isinstance(shaped, dict) or shaped.get("credential_type") != self.credential_type:
            raise ValueError("Proposify credential validator returned an invalid grant.")
        return shaped

    async def _load_principal(self, credential_id, principal_id, pool, org_id):
        from utils.encryption import get_encryption
        current_org = self.organization_id is CURRENT_ORGANIZATION
        row, org = await self._repo().load(
            credential_id, principal_id, org_id, caller_id=self.user_id,
            current_organization=current_org, workflow_id=self.workflow_id,
        )
        if row is None:
            return None
        # Admit raw row identity/live/version BEFORE touching the encrypted blob.
        version = row["token_version"]
        if (row["revoked_at"] is not None or row["credential_type"] != self.credential_type
                or type(version) is not int or version < 1):
            raise ValueError("Proposify credential is unavailable or its saved authority changed.")
        try:
            owner = str(UUID(str(row["owner_id"])))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Proposify credential saved owner is invalid.") from exc
        try:
            data = get_encryption().decrypt_credential(row["credential"])
        except Exception:
            raise ValueError("Proposify saved credential could not be decrypted.") from None
        if not isinstance(data, dict):
            raise ValueError("Proposify saved credential has an invalid shape.")
        data["credential_type"] = row["credential_type"]
        data = self._validated(data)
        self.current = CredentialAuthority(
            self.credential_id, self.user_id, str(principal_id), org, current_org,
            self.workflow_id, owner, row["credential_type"], version,
        )
        data = deepcopy(data)
        data["token_version"] = version
        if row["updated_at"] is not None:
            data["updated_at"] = row["updated_at"].isoformat()
        return data

    async def load(self):
        from utils.credentials import get_workflow_owner_id, is_credential_authorized_for_workflow
        self.current = None
        self._repo()
        org = None if self.organization_id is CURRENT_ORGANIZATION else self.organization_id
        # Staging's resolver returns only decrypted blobs, without the raw row
        # authority needed by this issued-token node. Use its existing owner and
        # authorization helpers, then recheck live access in the node's read query.
        data = await self._load_principal(self.credential_id, self.user_id, self.pool, org)
        if data is None and self.workflow_id:
            owner = await get_workflow_owner_id(self.pool, self.workflow_id)
            if (owner and str(owner) != self.user_id
                    and await is_credential_authorized_for_workflow(self.pool, self.workflow_id, self.credential_id)):
                data = await self._load_principal(self.credential_id, str(owner), self.pool, org)
        if data is None or self.current is None:
            raise ValueError("Proposify credential not found or current access denied.")
        return data




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


class ProposifyAuthorityRepo:
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
