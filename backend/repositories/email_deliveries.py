"""Deliveries of relayed mail to ``/email/inbound``, keyed by the relay's ``requestId``.

The relay queues each message it receives and delivers it until the backend
answers, so it retries a delivery whose answer it never got (a timeout, a
response lost on the way back) though the backend may have received it. A
delivery is claimed before it is handled, marked received once handled, and
given up if handling failed, so it can be tried again. A claim whose handler
died is taken over once its lease has run out; ``attempt`` fences the old
holder out of the row.
"""

from __future__ import annotations

import uuid
from typing import Optional

# Longer than any handling of one message (attachments stored and read); the relay retries a busy one later.
LEASE = "15 minutes"
# Longer than the relay keeps a message it can still deliver (its retries, then the dead-letter queue).
KEEP = "30 days"


class EmailDeliveryRepo:
    def __init__(self, pool):
        self.pool = pool

    async def claim(self, request_id: str) -> Optional[uuid.UUID]:
        """The attempt now holding ``request_id``'s delivery, or None if it was received or is being received."""
        await self.pool.execute(
            "DELETE FROM email_inbound_deliveries WHERE request_id IN (SELECT request_id "
            f"FROM email_inbound_deliveries WHERE claimed_at < now() - interval '{KEEP}' LIMIT 100)")
        return await self.pool.fetchval(
            f"""
            INSERT INTO email_inbound_deliveries (request_id) VALUES ($1)
            ON CONFLICT (request_id) DO UPDATE SET attempt = gen_random_uuid(), claimed_at = now()
              WHERE email_inbound_deliveries.received_at IS NULL
                AND email_inbound_deliveries.claimed_at < now() - interval '{LEASE}'
            RETURNING attempt
            """,
            request_id,
        )

    async def received(self, request_id: str) -> bool:
        return bool(await self.pool.fetchval(
            "SELECT received_at IS NOT NULL FROM email_inbound_deliveries WHERE request_id = $1", request_id))

    async def settle(self, request_id: str, attempt: uuid.UUID) -> None:
        await self.pool.execute(
            "UPDATE email_inbound_deliveries SET received_at = now() WHERE request_id = $1 AND attempt = $2",
            request_id, attempt)

    async def release(self, request_id: str, attempt: uuid.UUID) -> None:
        await self.pool.execute(
            "DELETE FROM email_inbound_deliveries WHERE request_id = $1 AND attempt = $2 AND received_at IS NULL",
            request_id, attempt)
