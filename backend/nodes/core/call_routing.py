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
    from utils.webhook_manager import registration_holder

    return await registration_holder(number_sid, (ON_CALL,), except_webhook_id=except_webhook_id)


def already_answers(number: str, holder: str) -> str:
    return (
        f"{number or 'This number'} already answers calls for {holder}. "
        f"A number can ring one agent; use another number for this one."
    )
