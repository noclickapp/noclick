"""Slack workspace installation store — the bot token chain of record.

Slack OAuth returns two token families:

- a workspace-scoped bot token, owned by the app *installation* in that team
- a per-user token (``authed_user``), owned by the human who authorized

Copying an installation token into multiple credential rows permits an older
sibling bundle to overwrite a newly rotated single-use refresh token. This
module replaces that copy-sync protocol
with ONE ``slack_installations`` row per installation key
``(team_id, app_id, client_id)``:

- ``resolve_slack_installation`` maps a credential to its installation row,
  seeding it from the newest sibling bundle on first touch (idempotent,
  ``ON CONFLICT DO NOTHING``).
- ``SlackInstallationStore`` is the row-of-record adapter for
  ``ensure_fresh_oauth_token`` — same lock + in-lock re-read + CAS persist
  discipline as the credentials table, against the installation row.
- ``ensure_fresh_slack_bot_token`` is the one entry point node code calls; it
  refreshes the installation chain if needed and merges the fresh bundle into
  the caller's credential dict.

Per-user (``user_*``) tokens stay on the credentials row and refresh through
the default store — they are per-human, not per-installation.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

# NOTE: nodes.core.oauth_refresh is imported lazily inside functions — node
# modules import this one at module level, and nodes/core pulls the node
# registry, so a top-level import here is a cycle.

logger = logging.getLogger(__name__)

# The complete bot-installation bundle. client_id/client_secret ride along so
# custom-OAuth-app installations refresh with their own client, not the env
# default.
_INSTALLATION_KEYS = (
    "access_token",
    "refresh_token",
    "expires_at",
    "scope",
    "token_type",
    "team_id",
    "team_name",
    "bot_user_id",
    "app_id",
    "client_id",
    "client_secret",
)


def _installation_bundle(data: Dict[str, Any]) -> Dict[str, Any]:
    return {k: data[k] for k in _INSTALLATION_KEYS if data.get(k) is not None}


def _matches_installation(candidate: Dict[str, Any], reference: Dict[str, Any]) -> bool:
    """Same-installation check: team must match; app_id / client_id only count
    as a mismatch when BOTH sides carry a value (older credentials predate
    app_id capture; '' and absent both mean unknown)."""
    if (candidate.get("team_id") or "") != (reference.get("team_id") or ""):
        return False
    for key in ("app_id", "client_id"):
        a, b = candidate.get(key) or "", reference.get(key) or ""
        if a and b and a != b:
            return False
    return True


class SlackInstallationStore:
    """Row-of-record adapter for ``ensure_fresh_oauth_token`` against
    ``slack_installations``. Mirrors ``CredentialsTableStore`` semantics:
    ``load()`` injects ``token_version``; ``persist()`` is a CAS on it (a DB
    trigger bumps the version on every bundle change)."""

    def __init__(self, pool, installation_id: str):
        self.pool = pool
        self.installation_id = installation_id

    @property
    def lock_key(self) -> str:
        return f"slack_installation:{self.installation_id}"

    async def load(self) -> Optional[Dict[str, Any]]:
        from utils.encryption import get_encryption

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT installation, revoked_at, token_version
                FROM slack_installations WHERE id = $1
                """,
                self.installation_id,
            )
        if not row:
            return None
        if row["revoked_at"] is not None:
            logger.warning(
                "[slack_installations] installation %s is revoked; refusing to load",
                self.installation_id,
            )
            return None
        bundle = get_encryption().decrypt_credential(row["installation"])
        bundle["token_version"] = row["token_version"]
        return bundle

    async def persist(
        self,
        new_data: Dict[str, Any],
        metadata_updates: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Optional[str]]:
        # metadata_updates is part of the store interface but installations
        # have no metadata column — expires_at/last_refreshed_at live in the
        # encrypted bundle itself.
        from utils.credentials import strip_non_blob_keys
        from utils.encryption import get_encryption

        try:
            encrypted = get_encryption().encrypt_credential(
                strip_non_blob_keys(_installation_bundle(new_data))
            )
            expected_version = new_data.get("token_version")
            async with self.pool.acquire() as conn:
                if expected_version is not None:
                    result = await conn.execute(
                        """
                        UPDATE slack_installations
                        SET installation = $1, revoked_at = NULL, revoked_reason = NULL
                        WHERE id = $2 AND token_version = $3
                        """,
                        encrypted, self.installation_id, expected_version,
                    )
                else:
                    result = await conn.execute(
                        """
                        UPDATE slack_installations
                        SET installation = $1, revoked_at = NULL, revoked_reason = NULL
                        WHERE id = $2
                        """,
                        encrypted, self.installation_id,
                    )
            try:
                rows = int(result.rsplit(" ", 1)[-1]) if isinstance(result, str) else 0
            except (ValueError, AttributeError):
                rows = 0
            return rows, None
        except Exception as e:
            logger.error(
                "[slack_installations] persist failed for %s: %s",
                self.installation_id, e, exc_info=True,
            )
            return 0, e.__class__.__name__

    async def mark_revoked(self, conn, reason: str) -> str:
        return await conn.execute(
            """
            UPDATE public.slack_installations
            SET revoked_at = NOW(), revoked_reason = $2
            WHERE id = $1::uuid AND revoked_at IS NULL
            """,
            self.installation_id,
            reason,
        )


async def resolve_slack_installation(
    pool, credential_data: Dict[str, Any]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Return ``(installation_id, bundle)`` for this credential's workspace.

    Seeds the installation row from the newest sibling credential bundle on
    first touch (one-time lazy migration of pre-normalization workspaces).
    Returns ``None`` for credentials without a ``team_id`` (manual bot tokens,
    non-OAuth). Raises if the installation was auto-revoked — every credential
    of the workspace is dead until someone reconnects.
    """
    team_id = credential_data.get("team_id")
    if not team_id:
        return None

    from utils.encryption import get_encryption

    encryption = get_encryption()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, app_id, client_id, installation, revoked_at, token_version "
            "FROM slack_installations WHERE team_id = $1",
            team_id,
        )
    match = _pick_installation_row(rows, credential_data)
    if match is None:
        match = await _seed_installation(pool, credential_data)
        if match is None:
            return None
    if match["revoked_at"] is not None:
        raise ValueError(
            f"Slack workspace connection for team {team_id} was revoked "
            f"({match.get('revoked_reason') or 'repeated refresh failures'}) — "
            f"reconnect Slack from Settings → Credentials"
        )
    bundle = encryption.decrypt_credential(match["installation"])
    bundle["token_version"] = match["token_version"]
    return str(match["id"]), bundle


def _pick_installation_row(rows, credential_data: Dict[str, Any]):
    """Exact (app_id, client_id) match first, then fuzzy (unknown matches
    anything) with the most specific row preferred."""
    app_id = credential_data.get("app_id") or ""
    client_id = credential_data.get("client_id") or ""
    fuzzy = None
    for row in rows:
        if row["app_id"] == app_id and row["client_id"] == client_id:
            return row
        if _matches_installation(
            {"team_id": credential_data.get("team_id"), "app_id": row["app_id"], "client_id": row["client_id"]},
            credential_data,
        ):
            if fuzzy is None or (row["app_id"] and not fuzzy["app_id"]):
                fuzzy = row
    return fuzzy


async def _seed_installation(pool, credential_data: Dict[str, Any]):
    """Create the installation row for a pre-normalization workspace.

    Gathers every sibling slack_oauth credential of the team, decrypts them,
    and seeds from the bundle with the NEWEST expires_at — older copies may
    hold an already-consumed rotating refresh token. Concurrent seeders are
    resolved by the UNIQUE key +
    ``ON CONFLICT DO NOTHING`` + re-select; no Slack call is made, so a lost
    insert race costs nothing.
    """
    from utils.encryption import get_encryption

    team_id = credential_data["team_id"]
    encryption = get_encryption()
    async with pool.acquire() as conn:
        sibling_rows = await conn.fetch(
            """
            SELECT credential FROM credentials
            WHERE credential_type = 'slack_oauth'
              AND metadata->>'team_id' = $1
            """,
            team_id,
        )
    candidates = [credential_data]
    for row in sibling_rows:
        try:
            sibling = encryption.decrypt_credential(row["credential"])
        except Exception:
            continue
        if _matches_installation(sibling, credential_data):
            candidates.append(sibling)
    best = max(candidates, key=lambda c: c.get("expires_at") or "")
    bundle = _installation_bundle(best)
    if not bundle.get("access_token"):
        return None

    encrypted = encryption.encrypt_credential(bundle)
    app_id = credential_data.get("app_id") or ""
    client_id = credential_data.get("client_id") or ""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO slack_installations (team_id, app_id, client_id, installation)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (team_id, app_id, client_id) DO NOTHING
            """,
            team_id, app_id, client_id, encrypted,
        )
        rows = await conn.fetch(
            "SELECT id, app_id, client_id, installation, revoked_at, token_version "
            "FROM slack_installations WHERE team_id = $1",
            team_id,
        )
    seeded = _pick_installation_row(rows, credential_data)
    if seeded is not None:
        logger.info(
            "[slack_installations] seeded installation %s for team %s from %d candidate bundle(s)",
            seeded["id"], team_id, len(candidates),
        )
    return seeded


async def ensure_fresh_slack_bot_token(
    pool,
    credential_data: Dict[str, Any],
    *,
    user_id: Optional[str],
    credential_id: Optional[str],
    force_refresh: bool = False,
    validate_when_fresh: bool = False,
    invalid_access_token: Optional[str] = None,
    caller_path: str = "unknown",
) -> Optional[str]:
    """Return a valid workspace bot token, refreshing the chain of record if
    needed, and merge the fresh bundle into *credential_data*.

    The chain of record is the workspace's ``slack_installations`` row when the
    credential carries a ``team_id``; a team-less rotating credential (no
    workspace key → no shared installation) refreshes its own row instead.
    Resolution is lazy: a locally fresh, unforced, unvalidated token returns
    without touching the database — same no-op cost as before normalization.

    ``validate_when_fresh`` replicates the freshen-path safety net: when the
    token did not need an expiry refresh, validate it against Slack and rotate
    the chain of record if Slack reports it invalid (revoked-but-unexpired).
    If the chain of record already moved past the invalid local copy, the
    newer bundle is adopted without burning another rotation.

    ``invalid_access_token`` is the caller-observed equivalent: the execute
    path passes the exact token Slack just rejected (``token_revoked`` on a
    locally-fresh copy — the blob's embedded token going stale after the
    installation chain rotated). It bypasses the local-fresh short-circuit and
    joins the same adopt-without-forcing guard, so a stale blob costs one
    retry instead of one single-use rotation per API call until blob expiry.
    ``credential_id`` is the triggering credential — forensic only; audit rows
    for an installation refresh carry the installation id.
    """
    from nodes.core.oauth_refresh import ensure_fresh_oauth_token, is_token_expired

    if not credential_data:
        return None
    access = credential_data.get("access_token")
    if not credential_data.get("refresh_token") and not credential_data.get("team_id"):
        return access  # manual bot token / non-rotating credential

    expires_at = credential_data.get("expires_at")
    local_fresh = not (expires_at and is_token_expired(expires_at))
    validate_failed = False
    if invalid_access_token and access == invalid_access_token:
        # The caller watched Slack reject exactly this token — local freshness
        # is a lie, so route through the chain of record.
        force_refresh = True
    if local_fresh and not force_refresh:
        if not (validate_when_fresh and access and credential_data.get("refresh_token")):
            return access
        from nodes.oauth.slack_oauth import validate_token

        is_valid, _ = await validate_token(access)
        if is_valid:
            return access
        # Revoked-but-unexpired — rotate via the chain of record.
        validate_failed = True
        force_refresh = True

    if pool is None:
        # Past the local-fresh short-circuit — first actual DB use.
        from utils.database_pool import get_native_pool

        pool = get_native_pool()
    resolved = await resolve_slack_installation(pool, credential_data)
    if resolved is None:
        # No workspace key — this credential row IS the chain of record.
        from nodes.oauth.slack_oauth import refresh_access_token

        async def refresh_local(refresh_token: str):
            return await refresh_access_token(
                refresh_token,
                credential_data.get("client_id"),
                credential_data.get("client_secret"),
            )

        return await ensure_fresh_oauth_token(
            pool=pool,
            credential_id=credential_id,
            user_id=user_id,
            credential=credential_data,
            refresh=refresh_local,
            is_expired=is_token_expired,
            force_refresh=force_refresh,
            provider="slack",
            caller_path=caller_path,
        )

    installation_id, bundle = resolved

    def _merge_back() -> None:
        credential_data.update(
            {k: bundle[k] for k in _INSTALLATION_KEYS if bundle.get(k) is not None}
        )

    if not bundle.get("refresh_token"):
        # Pre-rotation installation — nothing to refresh.
        _merge_back()
        return bundle.get("access_token")

    known_bad = access if validate_failed else invalid_access_token
    if known_bad and bundle.get("access_token") not in (None, known_bad):
        # The installation already rotated past the invalid local copy —
        # adopting it is enough; forcing would burn a rotation for nothing.
        force_refresh = False

    from nodes.oauth.slack_oauth import refresh_access_token

    async def refresh_fn(refresh_token: str):
        return await refresh_access_token(
            refresh_token, bundle.get("client_id"), bundle.get("client_secret")
        )

    store = SlackInstallationStore(pool, installation_id)
    token = await ensure_fresh_oauth_token(
        pool=pool,
        credential_id=installation_id,
        user_id=user_id or "system",
        credential=bundle,
        refresh=refresh_fn,
        is_expired=is_token_expired,
        force_refresh=force_refresh,
        provider="slack",
        caller_path=caller_path,
        store=store,
    )
    _merge_back()
    return token


async def upsert_slack_installation_from_exchange(
    pool, credential_data: Dict[str, Any]
) -> None:
    """Write the installation bundle after a fresh OAuth exchange.

    The new grant is authoritative — Slack rotates the workspace bot token on
    re-install, so the previous bundle (any sibling's) is dead the moment this
    exchange succeeds. Unconditional write (no CAS): version still bumps via
    the DB trigger, so concurrent CAS refreshers lose cleanly and re-read.
    """
    team_id = credential_data.get("team_id")
    bundle = _installation_bundle(credential_data)
    if not team_id or not bundle.get("access_token"):
        return

    from utils.encryption import get_encryption

    encrypted = get_encryption().encrypt_credential(bundle)
    app_id = credential_data.get("app_id") or ""
    client_id = credential_data.get("client_id") or ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, app_id, client_id, installation, revoked_at, token_version "
            "FROM slack_installations WHERE team_id = $1",
            team_id,
        )
        existing = _pick_installation_row(rows, credential_data)
        if existing is not None:
            await conn.execute(
                """
                UPDATE slack_installations
                SET installation = $1, revoked_at = NULL, revoked_reason = NULL
                WHERE id = $2
                """,
                encrypted, existing["id"],
            )
        else:
            await conn.execute(
                """
                INSERT INTO slack_installations (team_id, app_id, client_id, installation)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (team_id, app_id, client_id) DO UPDATE
                SET installation = EXCLUDED.installation,
                    revoked_at = NULL, revoked_reason = NULL
                """,
                team_id, app_id, client_id, encrypted,
            )
