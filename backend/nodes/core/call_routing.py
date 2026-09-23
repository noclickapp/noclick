"""What every node that answers calls on a phone number shares: a number
rings ONE agent. Routing rewrites the carrier's voice webhook, so a second
``on_call`` trigger on the same number would silently take every call while
the first still read "registered" — the registration refuses it by name."""

from __future__ import annotations

from typing import Optional

# The trigger operation every call-answering node uses; the voice function
# and the call-ended relay look it up by this name whichever node holds it.
ON_CALL = "on_call"


async def number_holder(number_sid: str, *, except_webhook_id: str) -> Optional[str]:
    """The workflow whose active on_call trigger already routes this number
    (its name, for the message), or None. The webhook row's
    external_webhook_id IS the number's provider id."""
    from utils.database_pool import get_native_pool

    row = await get_native_pool().fetchrow(
        """
        SELECT w.workflow_id, wf.name
        FROM webhooks w LEFT JOIN workflows wf ON wf.id = w.workflow_id
        WHERE w.external_webhook_id = $1 AND w.registered_operation = $2
          AND w.is_active AND w.id::text <> $3
        LIMIT 1
        """,
        number_sid, ON_CALL, except_webhook_id,
    )
    if row is None:
        return None
    return f'"{row["name"]}"' if row["name"] else f"workflow {row['workflow_id']}"


def already_answers(number: str, holder: str) -> str:
    return (
        f"{number or 'This number'} already answers calls for {holder}. "
        f"A number can ring one agent; use another number for this one."
    )
