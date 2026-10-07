"""Trusted current-row context for post-connect access hooks.

Only the authenticated handler creates this context. Provider labels and raw
credential metadata cannot authorize a stored probe or its final acceptance.
"""

from dataclasses import dataclass, field
from inspect import Parameter, signature
from typing import Any, Optional, TYPE_CHECKING

from repositories.credentials import CredentialsRepo, CredentialValidationRow

if TYPE_CHECKING:
    from nodes.core.connection_evidence import EvidenceResult


class CredentialValidationUnavailable(ValueError):
    """The canonical credential or its current authority cannot be used."""
    pass


class CredentialValidationUnverified(ValueError):
    """A probe did not establish access; it does not establish invalidity."""
    pass


class CredentialValidationPending(ValueError):
    def __init__(self, result):
        self.result = result
        super().__init__(result["message"])


def accepts_validation_context(hook):
    """An explicit keyword parameter opts in; arbitrary **kwargs does not."""
    try:
        parameter = signature(hook).parameters.get("validation_context")
    except (TypeError, ValueError):
        return False
    return parameter is not None and parameter.kind in {
        Parameter.KEYWORD_ONLY, Parameter.POSITIONAL_OR_KEYWORD,
    }


@dataclass(frozen=True)
class CredentialValidationContext:
    credential_id: str
    node_type: str
    user_id: str
    organization_id: Optional[str]
    pool: Any = field(repr=False, compare=False)
    _authority: CredentialValidationRow = field(repr=False)
    workflow_id: Optional[str] = None
    _results: list = field(default_factory=list, repr=False, compare=False)

    @classmethod
    async def create(cls, *, credential_id: str, node_type: str, user_id: str, pool: Any) -> "CredentialValidationContext":
        if not credential_id:
            raise CredentialValidationUnavailable("Credential is unavailable or access denied")
        from wss.handlers.workflow_handler import get_user_org_context
        async with pool.acquire() as conn:
            org_id = await get_user_org_context(conn, user_id)
        row = await CredentialsRepo(pool).fetch_validation_authority(credential_id, user_id, org_id)
        cls._require_available(row, node_type)
        return cls(credential_id, node_type, user_id, org_id, pool, row)

    @staticmethod
    def _require_available(row, node_type):
        if row is None or row.revoked_at is not None:
            raise CredentialValidationUnavailable("Credential is unavailable or access denied")
        from coder.workflow.operation_catalog import node_accepted_credential_types
        if row.credential_type not in node_accepted_credential_types(node_type):
            raise CredentialValidationUnavailable("Credential type is not supported by this node")

    async def revalidate(self) -> CredentialValidationRow:
        from wss.handlers.workflow_handler import get_user_org_context
        async with self.pool.acquire() as conn:
            org_id = await get_user_org_context(conn, self.user_id)
        if org_id != self.organization_id:
            raise CredentialValidationUnavailable("Credential access context changed; retry validation")
        row = await CredentialsRepo(self.pool).fetch_validation_authority(
            self.credential_id, self.user_id, org_id,
        )
        self._require_available(row, self.node_type)
        if row != self._authority:
            raise CredentialValidationUnavailable("Credential authority changed; retry validation")
        return row

    async def load_current_credential(self) -> dict[str, Any]:
        """Family, revocation, ownership, version and current ACL precede decrypt."""
        from utils.encryption import get_encryption
        row = await self.revalidate()
        data = get_encryption().decrypt_credential(row.credential)
        if not isinstance(data, dict):
            raise CredentialValidationUnavailable("Credential data is invalid")
        data = {**data, "credential_type": row.credential_type, "token_version": row.token_version}
        if row.updated_at is not None:
            data["updated_at"] = row.updated_at.isoformat()
        return data

    async def admit_probe(self):
        """A legacy class hook is a stored lookup, including token minting."""
        from utils.credential_approval import admit_lookup
        await self.revalidate()

        try:
            pending = await admit_lookup(
                credential_id=self.credential_id, user_id=self.user_id, node_type=self.node_type,
                arguments={"field_name": "__credential_access__", "context": {
                    "owner_id": self._authority.owner_id,
                    "credential_type": self._authority.credential_type,
                    "token_version": self._authority.token_version,
                    "updated_at": self._authority.updated_at.isoformat() if self._authority.updated_at else None,
                    "approval_revision": self._authority.approval_revision,
                }, "page_token": None, "search": None},
                pool=self.pool, organization_id=self.organization_id, workflow_id=self.workflow_id,
            )
        except Exception:
            # A failed probe must still retain a definite current-row denial.
            await self.revalidate()
            raise
        if pending:
            raise CredentialValidationPending(pending)
        await self.revalidate()

    async def _resolve_current_credential(self):
        from nodes.core.run_op import resolve_operation_credential
        await self.revalidate()
        try:
            data = await resolve_operation_credential(
                self.credential_id, self.user_id, self.pool, self.organization_id, self.workflow_id,
            )
        except Exception:
            await self.revalidate()
            raise
        await self.revalidate()
        if data.get("credential_type") != self._authority.credential_type:
            raise CredentialValidationUnavailable("Credential authority changed; retry validation")
        return data

    async def run_operation(self, operation: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Native checks keep their own factory, current resolver and admission."""
        attempt = len(self._results)
        self._results.append({"status": "error"})
        from nodes.core.registry import NODE_REGISTRY
        spec = getattr(NODE_REGISTRY[self.node_type], "connection_evidence", None)
        allowed = {"check_connection"}
        if spec is not None:
            allowed.update({spec.operation, spec.identity_operation})
        if operation not in allowed:
            raise ValueError("Only this node's declared connection checks can validate access")
        from nodes.core.run_op import run_node_operation
        data = await self._resolve_current_credential()
        try:
            result = await run_node_operation(
                node_type=self.node_type, operation=operation, arguments=arguments or {},
                credential_id=self.credential_id, user_id=self.user_id, pool=self.pool,
                organization_id=self.organization_id, workflow_id=self.workflow_id,
                credential_data=data,
            )
        except Exception:
            await self.revalidate()
            raise
        self._results[attempt] = result
        await self.revalidate()
        self._require_completed(result)
        return result

    async def collect_evidence(self) -> "EvidenceResult":
        attempt = len(self._results)
        self._results.append({"status": "error"})
        from nodes.core.registry import NODE_REGISTRY
        spec = getattr(NODE_REGISTRY[self.node_type], "connection_evidence", None)
        if spec is None or spec.field:
            # The field collector's trusted context/admission is a separate seam.
            raise ValueError("Use a declared native operation for this stored validation check")
        from nodes.core.connection_evidence import collect_evidence
        data = await self._resolve_current_credential()
        result = await collect_evidence(
            node_type=self.node_type, credential_id=self.credential_id,
            user_id=self.user_id, pool=self.pool, organization_id=self.organization_id,
            workflow_id=self.workflow_id,
            credential_data=data,
        )
        self._results[attempt] = {"status": "success" if result.reachable is True else "error"}
        await self.revalidate()
        if result.reachable is not True:
            raise CredentialValidationUnverified("The credential access probe did not complete successfully")
        return result

    @staticmethod
    def _require_completed(result):
        from nodes.core.connection_evidence import _raise_if_probe_not_executed, _raise_if_error_envelope
        if isinstance(result, dict) and result.get("status") in {"pending_approval", "rejected"}:
            raise CredentialValidationPending(result)
        if isinstance(result, dict) and (result.get("status") == "error" or result.get("success") is False):
            raise CredentialValidationUnverified("The credential access probe did not complete successfully")
        try:
            _raise_if_probe_not_executed(result)
            _raise_if_error_envelope(result)
        except Exception:
            raise CredentialValidationUnverified("The credential access probe did not complete successfully") from None

    async def accept(self, result):
        self._require_completed(result)
        for probe in self._results:
            self._require_completed(probe)
        await self.revalidate()
