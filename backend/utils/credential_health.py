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

    bound = {
        str(_row_field(row, "id")): (_row_field(row, "metadata") or {}).get("connection_id")
        for row in rows
    }
    # `require` makes an id the cache has never seen a refetch, not a verdict:
    # a just-scanned connection is younger than the cache.
    statuses = await get_connection_statuses(require=[c for c in bound.values() if c])
    if statuses is None:
        return {}

    out: Dict[str, CredentialHealth] = {}
    for cred_id, conn_id in bound.items():
        if not conn_id:
            continue  # legacy row without a connection binding — unknown, not dead
        # Absent from a FRESH WAHooks list = the connection is definitively gone.
        status = statuses.get(conn_id, "missing")
        healthy = status == "connected"
        out[cred_id] = CredentialHealth(
            status=status,
            healthy=healthy,
            hint=None if healthy else _RECONNECT_HINT.format(status=status),
        )
    return out


DISCORD_API_BASE = "https://discord.com/api/v10"
_DISCORD_REINSTALL_HINT = (
    "NoClick's Discord bot is no longer in {server} (Discord answered {status}). "
    "Reconnect Discord with 'Install bot' to add it back — until then this "
    "credential's message triggers and tools are dead."
)


async def _probe_discord_guild(client, guild_id: str) -> Optional[int]:
    """HTTP status of GET /guilds/{id} asked as the bot; None when Discord could
    not be asked at all."""
    try:
        return (await client.get(f"{DISCORD_API_BASE}/guilds/{guild_id}")).status_code
    except Exception as e:
        logger.warning(f"[CredentialHealth] Discord guild probe failed for {guild_id}: {e}")
        return None


async def _discord_bot_install_health(rows: Sequence[Any]) -> Dict[str, CredentialHealth]:
    """A bot-install credential is a server the bot was added to; the server's
    admin can remove the bot at any time and nothing in NoClick learns of it.
    Discord answering 403/404 for the guild is definitive; anything else is
    "cannot judge" (rate limit, outage, no platform token)."""
    import os

    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip().removeprefix("Bot ").strip()
    if not token:
        return {}
    guild_by_cred = {
        str(_row_field(row, "id")): str((_row_field(row, "metadata") or {}).get("guild_id") or "")
        for row in rows
    }
    guild_by_cred = {k: v for k, v in guild_by_cred.items() if v}
    if not guild_by_cred:
        return {}
    import httpx

    async with httpx.AsyncClient(timeout=10, headers={"Authorization": f"Bot {token}"}) as client:
        statuses = {gid: await _probe_discord_guild(client, gid) for gid in set(guild_by_cred.values())}
    out: Dict[str, CredentialHealth] = {}
    for row in rows:
        cred_id = str(_row_field(row, "id"))
        guild_id = guild_by_cred.get(cred_id)
        status = statuses.get(guild_id) if guild_id else None
        if status is None or status not in (200, 403, 404):
            continue  # unknown is never dead
        healthy = status == 200
        server = (_row_field(row, "metadata") or {}).get("guild_name") or guild_id
        out[cred_id] = CredentialHealth(
            status="installed" if healthy else "removed",
            healthy=healthy,
            hint=None if healthy else _DISCORD_REINSTALL_HINT.format(server=server, status=status),
        )
    return out


CREDENTIAL_HEALTH_CHECKS: Dict[str, Callable[[Sequence[Any]], Awaitable[Dict[str, CredentialHealth]]]] = {
    "whatsapp_qr": _whatsapp_qr_health,
    "discord_bot_install": _discord_bot_install_health,
}

#: The service name the owner reads in a disconnection email.
CREDENTIAL_HEALTH_LABELS: Dict[str, str] = {
    "whatsapp_qr": "WhatsApp",
    "discord_bot_install": "Discord",
}


async def _whatsapp_rescan_in_flight(row: Any, health: CredentialHealth) -> bool:
    """A bound WhatsApp connection sitting in scan_qr/pending while a QR flow
    holds its reservation is being re-scanned right now — not dead."""
    from utils.wahooks_connections import _has_active_reservation

    connection_id = (_row_field(row, "metadata") or {}).get("connection_id")
    return bool(
        health.status in ("scan_qr", "pending")
        and connection_id
        and await _has_active_reservation(str(connection_id))
    )


#: credential_type → "hold the email for this verdict" predicate.
DEAD_ALERT_EXEMPTIONS: Dict[str, Callable[[Any, CredentialHealth], Awaitable[bool]]] = {
    "whatsapp_qr": _whatsapp_rescan_in_flight,
}


async def alert_dead_credentials(pool) -> Dict[str, Any]:
    """Daily backstop for connection deaths no push path reported: owners of
    every in-use credential whose provider session is definitively dead get
    ONE email per credential per dedupe window (shared with any push path).
    Verdicts come from the same registry every picker and validator reads —
    a divergent rule here would email about a credential everyone else
    renders connected, or stay silent on one everyone renders dead."""
    from repositories.credentials import CredentialsRepo
    from utils.notifications import send_channel_disconnected_alert

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, owner_id, organization_id, credential_type, metadata FROM credentials "
            "WHERE credential_type = ANY($1::text[]) AND revoked_at IS NULL",
            list(CREDENTIAL_HEALTH_CHECKS),
        )
    health = await get_credential_health(rows)

    repo = CredentialsRepo(pool)
    alerted, dead_unreferenced = [], []
    for row in rows:
        cred_id = str(_row_field(row, "id"))
        verdict = health.get(cred_id)
        if verdict is None or verdict.healthy:
            continue
        ctype = _row_field(row, "credential_type")
        exemption = DEAD_ALERT_EXEMPTIONS.get(ctype)
        if exemption and await exemption(row, verdict):
            continue
        org_id = _row_field(row, "organization_id")
        referencing = await repo.list_workflows_referencing_credential(
            cred_id, str(_row_field(row, "owner_id")), str(org_id) if org_id else None
        )
        if not referencing:
            dead_unreferenced.append(cred_id)
            continue
        await send_channel_disconnected_alert(
            cred_id,
            provider_label=CREDENTIAL_HEALTH_LABELS.get(ctype, ctype),
            session_status=verdict.status,
            hint=verdict.hint,
            workflow_id=referencing[0]["workflow_id"],
            workflow_name=referencing[0]["workflow_name"],
            pool=pool,
        )
        alerted.append(cred_id)

    summary = {"credentials": len(rows), "alerted": alerted, "dead_unreferenced": dead_unreferenced}
    logger.info(f"[CredentialHealth] Dead-credential alert sweep: {summary}")
    return summary


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
