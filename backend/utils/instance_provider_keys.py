"""Instance-level model-provider keys for self-hosted installs.

The workflow builder's brain and any agent running on a server-side key read
provider keys from the environment. Supplying one used to mean editing
`backend/.env` and restarting; this stores them in `instance_provider_keys`
(encrypted at rest), applies them to `os.environ` at startup and after every
save, and lets the builder ask for the one it is missing right in the chat.

Same contract as instance OAuth apps (`utils/instance_oauth.py`): env-first
precedence, values this process applied are tagged so they can be rotated or
taken back without a restart, and every entry point is self-hosted only.
"""

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Dict, List, Optional

import os

from nodes.agent.config.providers import PROVIDER_REQUIRED_CREDENTIALS
from nodes.agent.key_validation import validate_provider_key
from utils.edition import is_local_edition
from utils.encryption import get_encryption
from utils.instance_env import apply_value, applied_by_store, release_value

logger = logging.getLogger(__name__)

_TAG_PREFIX = "_NC_INSTANCE_KEY_"

# The only names the store accepts: the provider keys the agent runtime itself
# knows how to use. Anything else would be an arbitrary write into the backend's
# environment from a browser session.
# Service keys the instance holds besides model providers: WAHooks issues the
# WhatsApp QR sessions (one key per instance, shared by everyone on it).
# Keys the instance holds for services that are not model providers: WhatsApp
# QR sign-in, the platform-keyed operations a self-hosted instance runs on its
# own key (nodes/core/platform_billing.py), and outbound email — an SMTP server
# or a Resend key, plus the sender address.
INSTANCE_SERVICE_ENV_VARS: tuple = (
    "WAHOOKS_API_KEY",
    "APIFY_API_TOKEN",
    "EXA_API_KEY",
    "PERPLEXITY_API_KEY",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "FROM_EMAIL",
    "RESEND_API_KEY",
)

SUPPORTED_ENV_VARS: tuple = tuple(
    sorted({name for names in PROVIDER_REQUIRED_CREDENTIALS.values() for name in names} | set(INSTANCE_SERVICE_ENV_VARS))
)


def env_configured() -> List[str]:
    """Supported keys the REAL environment defines (not ones applied from the
    store), so the UI can say a variable is already covered."""
    return [
        name for name in SUPPORTED_ENV_VARS
        if os.environ.get(name, "").strip() and not applied_by_store(name, _TAG_PREFIX)
    ]


async def list_keys(pool) -> List[Dict]:
    """Stored keys by name. Values are never returned."""
    rows = await pool.fetch(
        "SELECT env_var, updated_at FROM instance_provider_keys ORDER BY env_var"
    )
    return [
        {
            "env_var": r["env_var"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


async def set_key(pool, env_var: str, value: str, user_id: Optional[str]) -> None:
    if env_var not in SUPPORTED_ENV_VARS:
        raise ValueError(f"{env_var} is not a provider key this instance can store")
    value = (value or "").strip()
    if not value:
        raise ValueError("The key is empty")
    # The same live probe agent credentials get at connect time: a revoked or
    # creditless key is rejected here, in the form, rather than becoming the
    # builder's next "Generation failed".
    rejection = await validate_provider_key(env_var, value)
    if rejection:
        raise ValueError(rejection.message("instance"))
    encrypted = get_encryption().encrypt_credential({"value": value})
    await pool.execute(
        """
        INSERT INTO instance_provider_keys (env_var, value_encrypted, updated_by)
        VALUES ($1, $2, $3)
        ON CONFLICT (env_var) DO UPDATE
           SET value_encrypted = EXCLUDED.value_encrypted,
               updated_at = now(),
               updated_by = EXCLUDED.updated_by
        """,
        env_var, encrypted, user_id,
    )
    await apply_to_environment(pool)


async def delete_key(pool, env_var: str) -> None:
    await pool.execute("DELETE FROM instance_provider_keys WHERE env_var = $1", env_var)
    release_value(env_var, _TAG_PREFIX)


async def apply_to_environment(pool) -> int:
    """Copy stored keys into os.environ. A real environment value always wins;
    a value applied here earlier is replaced, so a rotated key takes effect on
    the next call rather than the next restart."""
    if not is_local_edition():
        return 0
    rows = await pool.fetch("SELECT env_var, value_encrypted FROM instance_provider_keys")
    applied = 0
    for row in rows:
        if row["env_var"] not in SUPPORTED_ENV_VARS:
            continue
        value = get_encryption().decrypt_credential(row["value_encrypted"]).get("value")
        if apply_value(row["env_var"], value, _TAG_PREFIX):
            applied += 1
    if applied:
        logger.info(f"[InstanceKeys] applied {applied} stored provider key(s) to the environment")
    return applied


SMTP_ENV_VARS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "FROM_EMAIL")


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    username: str
    password: str
    from_email: str


def probe_smtp(settings: SmtpSettings) -> Optional[str]:
    """Connect and log in the way a send would; the server's own words on failure.

    Unlike an API-key probe, an unreachable host IS a verdict here: the
    operator typed the address, and nothing can be sent through it anyway.
    """
    from utils.smtp_transport import smtp_client

    try:
        with smtp_client(settings.host, settings.port, timeout=10.0) as client:
            if settings.username:
                client.login(settings.username, settings.password)
    except smtplib.SMTPAuthenticationError as e:
        detail = e.smtp_error.decode(errors="replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        return f"{settings.host} rejected the login: {detail.strip()}"
    except (OSError, smtplib.SMTPException) as e:
        reason = (getattr(e, "strerror", None) or str(e)).strip()
        return f"Could not connect to {settings.host}:{settings.port} — {reason}"
    return None


async def set_smtp(pool, settings: SmtpSettings, user_id: Optional[str]) -> None:
    """Store the instance's SMTP transport after the server accepts a login."""
    if not parseaddr(settings.from_email)[1] or "@" not in parseaddr(settings.from_email)[1]:
        raise ValueError("Enter the sender as an address — name@yourdomain.com or Name <name@yourdomain.com>")
    rejection = await asyncio.wait_for(asyncio.to_thread(probe_smtp, settings), timeout=20)
    if rejection:
        raise ValueError(rejection)
    values = {
        "SMTP_HOST": settings.host,
        "SMTP_PORT": str(settings.port),
        "SMTP_USERNAME": settings.username,
        "SMTP_PASSWORD": settings.password,
        "FROM_EMAIL": settings.from_email,
    }
    for env_var, value in values.items():
        if value:
            await set_key(pool, env_var, value, user_id)
        else:
            await delete_key(pool, env_var)
