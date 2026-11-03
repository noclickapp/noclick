"""Self-echo suppression: NoClick-authored messages never trigger NoClick triggers.

A channel agent's reply can land on a chat another NoClick trigger listens to:
its own Slack trigger channel, or a second NoClick-linked WhatsApp number whose
agent answers back, and the two agents then talk to each other until credits run
out. Authorship fields can't identify every case (Slack ``send_as="user"`` posts
carry no ``bot_id``; another linked WhatsApp number is just a contact), so the
guard is exact: every message a NoClick node SENDS is fingerprinted here by its
provider message id, and the inbound path drops deliveries that match.

Fingerprints are deliberately global (not per-workflow): per-workflow keys
would still allow A→B→A cross-workflow loops. Same containment stance as
inbound email (which refuses senders on NoClick's mail domains). Chain
workflows directly, not via a chat.

Failure posture: recording must never fail the user's send, and a Redis blip
fails OPEN on the check (one extra fire, bounded by the fire budget) rather
than eating a real human message. Both paths log.

Timing: the fingerprint is written right after the send's HTTP response, and
the provider's echo must then traverse its own fan-out plus the receiver's
verify/parse/DB hops before the check runs, so in practice the SET wins by a
wide margin. A lost race means one extra fire, bounded by the fire budget.
"""

import logging
from typing import Optional

from utils.redis_client import get_shared_redis

logger = logging.getLogger(__name__)

# Comfortably past Slack's event-redelivery window (retries within ~1h);
# edits re-record on each chat.update, so a long TTL costs nothing.
SELF_POST_TTL_SECONDS = 6 * 60 * 60


def _key(provider: str, message_id: str) -> str:
    return f"{provider}:selfpost:{message_id}"


async def record_self_post(provider: str, message_id: Optional[str]) -> None:
    """Fingerprint a message NoClick just sent. Never raises: the send already
    succeeded and a guard bookkeeping failure must not fail the node run."""
    if not message_id:
        return
    client = get_shared_redis()
    if client is None:
        logger.warning(
            "[SelfEcho] REDIS_URL not set: %s self-post %s not recorded; "
            "a NoClick trigger may fire on this message",
            provider, message_id,
        )
        return
    try:
        await client.set(_key(provider, message_id), "1", ex=SELF_POST_TTL_SECONDS)
    except Exception as e:
        logger.warning(f"[SelfEcho] Failed to record {provider} self-post {message_id}: {e}")


async def is_self_post(provider: str, message_id: Optional[str]) -> bool:
    """Whether NoClick sent this message. Fails open (False) on Redis errors."""
    if not message_id:
        return False
    client = get_shared_redis()
    if client is None:
        return False
    try:
        return await client.exists(_key(provider, message_id)) > 0
    except Exception as e:
        # Fail open: one extra fire beats dropping a real human message.
        logger.warning(f"[SelfEcho] Fingerprint check failed for {provider} {message_id}: {e}")
        return False
