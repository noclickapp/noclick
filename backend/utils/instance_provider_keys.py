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

import logging
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
SUPPORTED_ENV_VARS: tuple = tuple(
    sorted({name for names in PROVIDER_REQUIRED_CREDENTIALS.values() for name in names})
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
