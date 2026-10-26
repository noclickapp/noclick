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
import secrets
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

# Each texting app's keys, saved and removed together (``set_texting``): what the operator copies from the provider,
# the value the instance makes for the provider's webhook, and what's read back from the provider.
TEXTING_ENV_VARS: Dict[str, tuple] = {
    "whatsapp": ("WHATSAPP_CLOUD_API_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_APP_SECRET",
                 "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "WHATSAPP_DISPLAY_NUMBER"),
    "imessage": ("SENDBLUE_API_KEY", "SENDBLUE_API_SECRET", "SENDBLUE_NUMBER", "SENDBLUE_WEBHOOK_SECRET"),
}
# The value the instance generates for each app's webhook, shown once when it's made.
TEXTING_WEBHOOK_SECRET = {"whatsapp": "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "imessage": "SENDBLUE_WEBHOOK_SECRET"}

# The only names the store accepts: the provider keys the agent runtime itself
# knows how to use. Anything else would be an arbitrary write into the backend's
# environment from a browser session.
# Service keys the instance holds besides model providers: WAHooks issues the
# WhatsApp QR sessions (one key per instance, shared by everyone on it).
# Keys the instance holds for services that are not model providers: WhatsApp
# QR sign-in, the Discord bot whose Gateway session delivers channel-message
# triggers (utils/discord_gateway_bridge.py), the platform-keyed operations a
# self-hosted instance runs on its own key (nodes/core/platform_billing.py),
# outbound email — an SMTP server or a Resend key, plus the sender address — and the
# lines people text the assistant on (WhatsApp's Cloud API, a Sendblue iMessage line).
INSTANCE_SERVICE_ENV_VARS: tuple = (
    "WAHOOKS_API_KEY",
    "DISCORD_BOT_TOKEN",
    "APIFY_API_TOKEN",
    "DECODO_AUTH_TOKEN",
    "EXA_API_KEY",
    "PERPLEXITY_API_KEY",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "FROM_EMAIL",
    "RESEND_API_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_VERIFY_SERVICE_SID",
    *TEXTING_ENV_VARS["whatsapp"],
    *TEXTING_ENV_VARS["imessage"],
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
    await _store(pool, {env_var: value}, user_id)


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


async def _store(pool, values: Dict[str, str], user_id: Optional[str]) -> None:
    """Store several keys at once, then apply them together."""
    for env_var, value in values.items():
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


async def set_texting(pool, app: str, fields: Dict[str, str], user_id: Optional[str]) -> Dict[str, str]:
    """Store one texting app's keys after the provider accepts them (``app`` "whatsapp": the Cloud API token, the
    phone number id and the app secret; "imessage": Sendblue's API key and secret and the line). The secret its
    webhook is checked against is made here the first time; returns it, by name, when it was just made (it's shown
    then, never read back)."""
    from utils.phone_numbers import normalize_e164

    names = TEXTING_ENV_VARS.get(app)
    if names is None:
        raise ValueError("app must be whatsapp or imessage")
    typed = {name: (fields.get(name) or "").strip() for name in names[:3]}
    missing = [name for name, value in typed.items() if not value]
    if missing:
        raise ValueError(f"Fill in {', '.join(missing)}")
    if app == "whatsapp":
        from utils.whatsapp_cloud_api import CloudApi, WhatsAppSendError

        try:
            number = await CloudApi(typed["WHATSAPP_CLOUD_API_TOKEN"], typed["WHATSAPP_PHONE_NUMBER_ID"]).phone_number()
        except WhatsAppSendError as exc:
            raise ValueError(str(exc)) from exc
        shown = str(number.get("display_phone_number") or "")
        display = normalize_e164(shown if shown.startswith("+") else f"+{shown}")
        if display is None:
            raise ValueError(f"WhatsApp lists this number as {shown!r}, which isn't a full international number")
        typed["WHATSAPP_DISPLAY_NUMBER"] = display
    else:
        from utils.sendblue import Sendblue, SendblueError

        line = normalize_e164(typed["SENDBLUE_NUMBER"])
        if line is None:
            raise ValueError("Enter the line with its country code, like +1 415 555 0100")
        typed["SENDBLUE_NUMBER"] = line
        try:
            await Sendblue(typed["SENDBLUE_API_KEY"], typed["SENDBLUE_API_SECRET"], line).check_keys()
        except SendblueError as exc:
            raise ValueError(f"Sendblue refused the keys: {exc}") from exc
    made: Dict[str, str] = {}
    secret_var = TEXTING_WEBHOOK_SECRET[app]
    stored = {r["env_var"] for r in await pool.fetch("SELECT env_var FROM instance_provider_keys")}
    if secret_var not in stored and secret_var not in env_configured():
        made[secret_var] = secrets.token_urlsafe(24)
    await _store(pool, {**typed, **made}, user_id)
    return made


def texting_state() -> Dict[str, Dict]:
    """Each texting app as Settings shows it: whether its keys are in, the line, the webhook URL to give the
    provider, where the links it texts open (the app's address), and whether texting can run here at all (Redis
    counts link codes, notices and redeliveries)."""
    from coder.coordinator.texting.routes import IMESSAGE_PATH, WHATSAPP_PATH
    from utils.hosted_defaults import frontend_url
    from utils.redis_client import redis_url_or_none
    from utils.webhook_delivery import get_webhook_base_url

    base = get_webhook_base_url()
    app_url = frontend_url()
    lines = {"whatsapp": "WHATSAPP_DISPLAY_NUMBER", "imessage": "SENDBLUE_NUMBER"}
    paths = {"whatsapp": WHATSAPP_PATH, "imessage": IMESSAGE_PATH}
    return {
        app: {
            "configured": all(os.environ.get(name, "").strip() for name in names),
            "line": os.environ.get(lines[app], "").strip() or None,
            "webhook_url": f"{base}{paths[app]}" if base else None,
            "app_url": app_url,
            "redis": redis_url_or_none() is not None,
        }
        for app, names in TEXTING_ENV_VARS.items()
    }
