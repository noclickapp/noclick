"""Read current Supernormal token authority before and after provider calls.

Keep row identity and access anchors separate from the issued token blob.
"""
from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID

from nodes.supernormal_authority_repository import SupernormalAuthorityRepo

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


class SupernormalAuthorityStore:
    requires_current_authority = True

    def __init__(self, pool, user_id, credential_id, *, credential_type,
                 validate, grant_fields=(), organization_id=CURRENT_ORGANIZATION,
                 workflow_id=None, require_owner=False, allow_same_grant_retry=True):
        self.pool = pool
        self.user_id = str(UUID(str(user_id)))
        self.credential_id = str(UUID(str(credential_id)))
        self.credential_type = credential_type
        self.validate = validate
        self.grant_fields = tuple(grant_fields)
        self.organization_id = organization_id
        self.workflow_id = str(UUID(str(workflow_id))) if workflow_id else None
        self.require_owner = require_owner
        self.allow_same_grant_retry = allow_same_grant_retry
        self.current = None
        self.submitted = None
        self.submitted_grant = None
        self.minted_grant = None
        self._grant_keys = ()

    @property
    def lock_key(self):
        return self.credential_id

    def _repo(self):
        if self.pool is None:
            from utils.database_pool import get_native_pool
            self.pool = get_native_pool()
        return SupernormalAuthorityRepo(self.pool)

    def _validated(self, data):
        try:
            shaped = self.validate(data)
        except Exception:
            # Model and provider-validation input details can contain tokens.
            raise ValueError("OAuth credential grant shape or binding is invalid.") from None
        if not isinstance(shaped, dict) or shaped.get("credential_type") != self.credential_type:
            raise ValueError("OAuth credential validator returned an invalid grant.")
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
            raise ValueError("OAuth credential is unavailable or its saved authority changed.")
        try:
            owner = str(UUID(str(row["owner_id"])))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("OAuth credential saved owner is invalid.") from exc
        if self.require_owner and owner != self.user_id:
            raise ValueError("Only the current credential owner may refresh this connection.")
        try:
            data = get_encryption().decrypt_credential(row["credential"])
        except Exception:
            raise ValueError("OAuth saved credential could not be decrypted.") from None
        if not isinstance(data, dict):
            raise ValueError("OAuth saved credential has an invalid shape.")
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
        data = await self._load_principal(self.credential_id, self.user_id, self.pool, org)
        if data is None and self.workflow_id and not self.require_owner:
            owner = await get_workflow_owner_id(self.pool, self.workflow_id)
            if (owner and str(owner) != self.user_id
                    and await is_credential_authorized_for_workflow(self.pool, self.workflow_id, self.credential_id)):
                data = await self._load_principal(self.credential_id, str(owner), self.pool, org)
        if data is None or self.current is None:
            raise ValueError("OAuth credential not found or current access denied.")
        return data
