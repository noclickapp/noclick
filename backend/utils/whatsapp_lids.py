"""Which phone number a WhatsApp ``@lid`` chat stands for, per connection.

WhatsApp names more and more chats by a privacy id (``…@lid``) instead of the
number. A message from such a chat still says who wrote it (WAHooks'
``senderPhone``, read from WhatsApp's own ``remoteJidAlt``), so each delivery
records the pair here, and a recipient scope written as numbers can match the
chat an allowed person writes from. WAHA's contact book holds none of these
pairs on most accounts (2026-11-03), so deliveries are the only source. A pair
NoClick never saw, or Redis lost, leaves the chat known by its @lid alone.
"""

import logging
from typing import Dict, Iterable, Optional

from utils import redis_client

logger = logging.getLogger(__name__)

TTL_S = 180 * 24 * 3600  # A pair never changes; kept while the chat stays in use.


def _key(connection_id: str) -> str:
    return f"wa:lids:{connection_id}"


async def remember(connection_id: Optional[str], lid: str, phone: str) -> None:
    """Record that ``lid`` writes from ``phone`` (its digits) on this connection."""
    client = redis_client.get_shared_redis()
    if client is None or not connection_id or not lid.endswith("@lid") or not phone:
        return
    try:
        await client.hset(_key(connection_id), lid, phone)
        await client.expire(_key(connection_id), TTL_S)
    except Exception as e:
        logger.warning(f"[WhatsAppLids] Could not record a chat's number for {connection_id}: {e}")


async def phones(connection_id: Optional[str], lids: Iterable[str]) -> Dict[str, str]:
    """The numbers recorded for ``lids`` on this connection, by lid."""
    wanted = sorted({lid for lid in lids if lid.endswith("@lid")})
    client = redis_client.get_shared_redis()
    if client is None or not connection_id or not wanted:
        return {}
    try:
        found = await client.hmget(_key(connection_id), wanted)
    except Exception as e:
        logger.warning(f"[WhatsAppLids] Could not read chats' numbers for {connection_id}: {e}")
        return {}
    return {
        lid: phone.decode() if isinstance(phone, bytes) else str(phone)
        for lid, phone in zip(wanted, found) if phone
    }
