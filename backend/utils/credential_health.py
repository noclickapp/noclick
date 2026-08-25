"""Provider-session health for connection-backed credentials.

Some credential types are backed by a live provider-side session (whatsapp_qr →
a WAHA phone link via WAHooks) that can die independently of the stored secret.
A dead session makes every run and tool call silently useless while the
credential row still looks attached, so every surface that reasons about
credentials — the picker, workflow validation, the builder brain,
describe_workflow — must consult ONE health source instead of assuming
attached == working. A stale provider session must be surfaced as unhealthy
instead of allowing validation and registration to treat it as connected.

Registry seam: ``CREDENTIAL_HEALTH_CHECKS`` maps credential_type → an async
checker over all rows of that type at once (one provider round-trip covers the
account). Doctrine: unknown is NEVER dead — a checker that cannot reach its
provider returns no verdicts rather than guessing, and callers must treat
absent rows as healthy (non-definitive-signal, same stance as webhook/cron
teardown).
"""

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CredentialHealth:
    status: str          # provider-native session state (e.g. 'connected', 'failed', 'missing')
    healthy: bool
    hint: Optional[str]  # actionable guidance when unhealthy, phrased for humans AND agents


def _row_field(row: Any, name: str) -> Any:
    # .get first: covers dicts AND asyncpg Records (which are mappings but
    # neither dict instances nor attribute-accessible — getattr on a Record
    # returns None for every column and silently voids the health map).
    if hasattr(row, "get"):
        return row.get(name)
    return getattr(row, name, None)


def health_relevant_credential_ids(config: Any) -> List[str]:
    """Credential UUIDs in a node config's ``credentialIds`` map whose KEY is a
    health-checked type — the pre-filter that lets callers skip the DB/provider
    round-trip entirely for the ~all workflows with no connection-backed
    credentials. Key-filtering fails open: a credential attached under a
    non-standard key just keeps today's plain ✓ rendering. Values are filtered
    through ``_is_credential_uuid`` so ``{{vars.X}}`` refs and marker keys
    never reach a ``uuid[]`` cast (which would abort the whole fetch)."""
    from utils.credentials import _is_credential_uuid

    cred_ids = (config or {}).get("credentialIds") if isinstance(config, dict) else None
    if not isinstance(cred_ids, dict):
        return []
    return [
        str(v)
        for k, v in cred_ids.items()
        if k in CREDENTIAL_HEALTH_CHECKS and _is_credential_uuid(v)
    ]


_RECONNECT_HINT = (
    "WhatsApp phone link is dead (session {status}). Re-scan the QR code for "
    "THIS credential to restore it — do not create a new credential; repeated "
    "fresh scans can get all of the phone's links logged out by WhatsApp."
)


async def _whatsapp_qr_health(rows: Sequence[Any]) -> Dict[str, CredentialHealth]:
    from utils.whatsapp_qr import get_connection_statuses

    statuses = await get_connection_statuses()
    if statuses is None:
        return {}

    out: Dict[str, CredentialHealth] = {}
    for row in rows:
        conn_id = (_row_field(row, "metadata") or {}).get("connection_id")
        if not conn_id:
            continue  # legacy row without a connection binding — unknown, not dead
        # Absent from WAHooks = the connection is definitively gone.
        status = statuses.get(conn_id, "missing")
        healthy = status == "connected"
        out[str(_row_field(row, "id"))] = CredentialHealth(
            status=status,
            healthy=healthy,
            hint=None if healthy else _RECONNECT_HINT.format(status=status),
        )
    return out


CREDENTIAL_HEALTH_CHECKS: Dict[str, Callable[[Sequence[Any]], Awaitable[Dict[str, CredentialHealth]]]] = {
    "whatsapp_qr": _whatsapp_qr_health,
}


async def fetch_credential_health_for_ids(pool, credential_ids: Sequence[str]) -> Dict[str, CredentialHealth]:
    """Health verdicts for credential ids referenced by a workflow graph —
    the pre-fetch that populates ``GraphState._credential_health`` before the
    sync XML/summary renderers run. Fails open to {} (unknown, never dead)."""
    if not credential_ids:
        return {}
    try:
        from repositories.credentials import CredentialsRepo

        rows = await CredentialsRepo(pool).fetch_health_probe_rows(
            list(credential_ids), credential_types=list(CREDENTIAL_HEALTH_CHECKS)
        )
        return await get_credential_health(rows)
    except Exception as e:
        logger.warning(f"[CredentialHealth] pre-fetch failed: {e}")
        return {}


async def get_credential_health(rows: Sequence[Any]) -> Dict[str, CredentialHealth]:
    """id → health for every row whose type has a checker AND whose provider
    answered. Rows absent from the result are unknown-or-not-applicable and
    must be treated as healthy. ``rows`` are dicts or objects carrying
    ``id`` / ``credential_type`` / ``metadata``.
    """
    by_type: Dict[str, List[Any]] = {}
    for row in rows:
        ctype = _row_field(row, "credential_type")
        if ctype in CREDENTIAL_HEALTH_CHECKS:
            by_type.setdefault(ctype, []).append(row)

    out: Dict[str, CredentialHealth] = {}
    for ctype, typed_rows in by_type.items():
        try:
            out.update(await CREDENTIAL_HEALTH_CHECKS[ctype](typed_rows))
        except Exception as e:
            # Unknown, never dead: a failing checker yields no verdicts.
            logger.warning(f"[CredentialHealth] {ctype} checker failed: {e}")
    return out
