"""Instance-level OAuth app credentials for self-hosted installs.

A self-hoster registers their own OAuth app per provider (the hosted service's
client IDs are bound to its own callback URLs). Supplying one used to mean
editing `backend/.env` and `frontend/.env` and restarting both processes; this
lets them paste it into Settings instead.

The store is `instance_oauth_apps`, one row per provider. Rather than teach 56
`get_<provider>_client_config()` functions about a second source, stored values
are applied to `os.environ` at startup and again after every save — so every
existing reader, including ones added later, picks them up with no change.

Precedence is env-first and enforced by that same application step: a name
already present in the environment is never overwritten. An operator who
configures through env vars or a secret manager is unaffected by this table, and
`env_configured_providers()` reports which providers the environment already
covers, so the UI can say so instead of pretending the form is authoritative.

Hosted installs don't use this at all — `is_local_edition()` gates every entry
point, and the Settings tab that writes it is self-hosted only.
"""

import logging
import os
from typing import Dict, List, Optional

from utils.edition import is_local_edition
from utils.encryption import get_encryption
from utils.instance_env import apply_value, applied_by_store, release_value

logger = logging.getLogger(__name__)

# Marks an env var this module set from the database, so deletion can take back
# only what it added and the env-vs-stored report can tell the two apart.
_TAG_PREFIX = "_NC_INSTANCE_OAUTH_"


# Providers whose readers don't use the <PROVIDER>_CLIENT_ID/_SECRET convention.
# Deriving the names mechanically is right for 48 of 49, and silently wrong for
# the rest: the value lands in a variable nothing reads, so saving an app appears
# to work and the connect flow still reports it unconfigured.
# `frontend/tests/routes/oauthAuthorizeEnvNames.test.ts` fails when a route reads
# a name no one sets, so a new exception can't stay silent.
_ENV_NAME_OVERRIDES = {
    "facebook": ("FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET"),
    "meta": ("META_APP_ID", "META_APP_SECRET"),
    "tiktok": ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"),
}


def _env_names(provider: str) -> tuple:
    """(client_id_var, client_secret_var) for a provider key."""
    if provider in _ENV_NAME_OVERRIDES:
        return _ENV_NAME_OVERRIDES[provider]
    stem = provider.upper()
    return f"{stem}_CLIENT_ID", f"{stem}_CLIENT_SECRET"


async def list_apps(pool) -> List[Dict]:
    """Configured providers with their client ids. Secrets are never returned —
    the UI shows whether one is set, not what it is."""
    rows = await pool.fetch(
        """
        SELECT provider, client_id,
               client_secret_encrypted IS NOT NULL AS has_secret,
               updated_at
          FROM instance_oauth_apps
         ORDER BY provider
        """
    )
    return [
        {
            "provider": r["provider"],
            "client_id": r["client_id"],
            "has_secret": r["has_secret"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


def env_configured_providers() -> List[str]:
    """Providers whose client id comes from the REAL environment.

    Excludes what `apply_to_environment` put there itself — otherwise every app
    saved through Settings would report back as environment-configured a moment
    later, and the UI would tell the operator their own entry was inert.

    Worth surfacing in its own right: without it, someone who set
    LINEAR_CLIENT_ID in a .env file sees "Not configured" in Settings and has no
    way to tell that the environment already has it covered.
    """
    # Reverse the override map so a provider with an off-convention name (see
    # _ENV_NAME_OVERRIDES) is still recognised as environment-configured.
    by_id_var = {_env_names(p)[0]: p for p in _ENV_NAME_OVERRIDES}

    found = []
    for name, value in os.environ.items():
        if not value or not (name.endswith("_CLIENT_ID") or name in by_id_var):
            continue
        # The tag below is itself named <PROVIDER>_CLIENT_ID with a prefix, so it
        # ends in _CLIENT_ID too and matched — reporting a provider literally
        # called "_nc_instance_oauth_linear". Skip the bookkeeping namespace.
        if name.startswith(_TAG_PREFIX):
            continue
        if applied_by_store(name, _TAG_PREFIX):
            continue  # we set this one from the database
        found.append(by_id_var.get(name) or name[: -len("_CLIENT_ID")].lower())
    return sorted(found)


async def upsert_app(pool, provider: str, client_id: str, client_secret: Optional[str], user_id: Optional[str]) -> None:
    """Store one provider's app. A None secret leaves any existing one intact —
    the UI never round-trips the secret, so an edit to the client id alone must
    not silently blank it."""
    encrypted = (
        get_encryption().encrypt_credential({"client_secret": client_secret})
        if client_secret
        else None
    )
    await pool.execute(
        """
        INSERT INTO instance_oauth_apps (provider, client_id, client_secret_encrypted, updated_by)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (provider) DO UPDATE
           SET client_id = EXCLUDED.client_id,
               client_secret_encrypted = COALESCE(EXCLUDED.client_secret_encrypted,
                                                  instance_oauth_apps.client_secret_encrypted),
               updated_at = now(),
               updated_by = EXCLUDED.updated_by
        """,
        provider, client_id, encrypted, user_id,
    )
    await apply_to_environment(pool)


async def delete_app(pool, provider: str) -> None:
    """Forget a provider's app, and drop the values it put in the environment so
    the change takes effect without a restart."""
    await pool.execute("DELETE FROM instance_oauth_apps WHERE provider = $1", provider)
    for name in _env_names(provider):
        release_value(name, _TAG_PREFIX)


async def apply_to_environment(pool) -> int:
    """Copy stored apps into os.environ, never overwriting what's already there.

    Values this function set are tagged so `delete_app` can take them back out
    again; a value that came from the real environment is left alone forever.
    """
    if not is_local_edition():
        return 0
    rows = await pool.fetch(
        "SELECT provider, client_id, client_secret_encrypted FROM instance_oauth_apps"
    )
    applied = 0
    for row in rows:
        client_id_var, client_secret_var = _env_names(row["provider"])
        secret = None
        if row["client_secret_encrypted"]:
            secret = get_encryption().decrypt_credential(row["client_secret_encrypted"]).get("client_secret")
        for name, value in ((client_id_var, row["client_id"]), (client_secret_var, secret)):
            if apply_value(name, value, _TAG_PREFIX):
                applied += 1
    if applied:
        logger.info(f"[InstanceOAuth] applied {applied} stored value(s) to the environment")
    return applied
