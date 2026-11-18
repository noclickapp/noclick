"""Feedback: a note to the NoClick team."""

from __future__ import annotations

from typing import Optional

from ._client import Client, resolve_client
from ._sync import synced

KINDS = ("bug", "idea", "general")


@synced
async def feedback(message: str, *, kind: str = "general", client: Optional[Client] = None) -> None:
    """Tell the NoClick team something: a ``bug``, an ``idea``, or anything (``general``).
    It reaches them as the app's feedback button does, from any key, an agent's
    included; an account sends up to 20 a day (``RateLimited`` past that).

    Usage::

        noclick.feedback("Agent.list could filter by workflow.", kind="idea")
    """
    if kind not in KINDS:
        raise ValueError(f"kind is one of {KINDS}, not {kind!r}")
    await resolve_client(client).request("POST", "/v1/feedback", json={"message": message, "kind": kind}, user=None)
