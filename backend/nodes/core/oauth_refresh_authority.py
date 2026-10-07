"""Opt-in stored OAuth authority for the common refresh manager.

Provider validators and workflow context are trusted source-level inputs.
Actual SQL identity/access anchors remain private to this adapter, outside the
provider credential blob. Legacy refresh stores keep their existing contract.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
from uuid import UUID

from repositories.oauth_refresh_authority import OAuthRefreshAuthorityRepo

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


class AuthorityCredentialsTableStore:
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
        return OAuthRefreshAuthorityRepo(self.pool)

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
        from utils.credentials import resolve_credential_with_owner_fallback
        self.current = None
        self._repo()
        org = None if self.organization_id is CURRENT_ORGANIZATION else self.organization_id
        data = await resolve_credential_with_owner_fallback(
            self.credential_id, self.user_id, self.pool, org_id=org,
            workflow_id=None if self.require_owner else self.workflow_id,
            load_credential_fn=self._load_principal,
        )
        if data is None or self.current is None:
            raise ValueError("OAuth credential not found or current access denied.")
        return data

    def _grant(self, data):
        # Explicit missing/None normalization; canonical JSON makes nested
        # app/account fields immutable independently of common dict mutation.
        return json.dumps({key: data.get(key) for key in self._grant_keys},
                          sort_keys=True, separators=(",", ":"), allow_nan=False)

    def begin_refresh(self, data, *, access_token_key, refresh_token_key,
                      expires_at_key, additional_token_fields):
        if self.current is None:
            raise ValueError("OAuth refresh requires current saved authority.")
        self._grant_keys = tuple(dict.fromkeys((
            "credential_type", access_token_key, refresh_token_key, expires_at_key,
            "scope", "token_type", *self.grant_fields, *additional_token_fields,
        )))
        self.submitted = self.current
        self.submitted_grant = self._grant(deepcopy(data))
        self.minted_grant = None

    def finish_refresh(self, data):
        validated = self._validated(deepcopy(data))
        self.minted_grant = self._grant(validated)
        validated = deepcopy(validated)
        validated["token_version"] = data["token_version"]
        if "updated_at" in data:
            validated["updated_at"] = data["updated_at"]
        return validated

    def can_merge(self, data):
        # A version-only/non-grant update may retain the submitted authority.
        # Never move an older mint into a new owner or resolved access context.
        authority_fields = ("credential_id", "caller_id", "principal_id",
                            "organization_id", "current_organization",
                            "workflow_id", "owner_id", "credential_type")
        return (self.allow_same_grant_retry and self.submitted is not None
                and self.current is not None and self.submitted_grant is not None
                and all(getattr(self.current, key) == getattr(self.submitted, key)
                        for key in authority_fields)
                and self._grant(data) == self.submitted_grant)

    async def persist(self, new_data, metadata_updates=None):
        from utils.credentials import strip_non_blob_keys
        from utils.encryption import get_encryption
        if (self.current is None or self.minted_grant is None
                or new_data.get("token_version") != self.current.token_version
                or self._grant(new_data) != self.minted_grant):
            raise ValueError("OAuth refreshed grant does not match its saved authority.")
        data = self._validated(deepcopy(new_data))
        if self._grant(data) != self.minted_grant:
            raise ValueError("OAuth refreshed grant changed before persistence.")
        try:
            encrypted = get_encryption().encrypt_credential(strip_non_blob_keys(data))
            return await self._repo().persist(self.current, encrypted, metadata_updates), None
        except Exception as exc:
            return 0, type(exc).__name__

    async def mark_revoked(self, conn, reason):
        # Failure recovery load() never upgrades the submitted failure anchor.
        if self.submitted is None or self.minted_grant is not None:
            return "UPDATE 0"
        return await OAuthRefreshAuthorityRepo.mark_revoked(conn, self.submitted, reason)
