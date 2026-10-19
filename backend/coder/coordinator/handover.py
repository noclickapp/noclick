"""Where an agent answers the account's owner in the coordinator's place (``ACCOUNT_AGENT``), whatever would have
woken the coordinator reaches that agent instead: the agent is made first where the account is meant to have one,
so nothing wakes the coordinator, or starts its own thread, for an account that has moved. Work the coordinator
started before finishes on its own ledger, and its outcome is handed over (``ACCOUNT_AGENT_HANDOVER``)."""

from __future__ import annotations

import json
from typing import Any, Dict

from utils.prompts import PromptPack

PROMPTS = PromptPack("coordinator")

# What a wake-up's note holds (cloud/platform/agents: a note is at most 4,000 characters).
NOTE_CHARS = 4000


async def agent_answers(pool, user_id: str) -> bool:
    """Whether an agent answers this account's owner, made first where the account is meant to have one."""
    from utils.capabilities import ACCOUNT_AGENT, capability

    agent = capability(ACCOUNT_AGENT)
    return agent is not None and await agent(pool, user_id, ensure=True) is not None


async def hand_over(pool, user_id: str, note: str, *, from_outside: bool = False) -> bool:
    """``note`` as a wake-up of the agent that answers the account's owner; False where none does."""
    from utils.capabilities import ACCOUNT_AGENT_HANDOVER, capability

    hand = capability(ACCOUNT_AGENT_HANDOVER)
    return hand is not None and await hand(pool, user_id, note[:NOTE_CHARS], from_outside=from_outside) is not None


def _fitting(value: Any, room: int) -> str:
    """``value`` as JSON in at most ``room`` characters, its strings and lists clipped until it fits."""
    from utils.previews import bounded

    for max_chars, max_items in ((1500, 20), (600, 10), (200, 5), (60, 3)):
        text = json.dumps(bounded(value, max_chars=max_chars, max_items=max_items), ensure_ascii=False, default=str)
        if len(text) <= room:
            return text
    return text[:room]


async def hand_over_wakeup(pool, event: Dict[str, Any]) -> bool:
    """A coordinator wake-up handed to the agent that answers its account (its note composed only then)."""
    from coder.coordinator.agent import UNTRUSTED_WAKEUPS

    user_id = str(event["user_id"])
    return await agent_answers(pool, user_id) and await hand_over(
        pool, user_id, wakeup_note(event), from_outside=event["source"] in UNTRUSTED_WAKEUPS)


def wakeup_note(event: Dict[str, Any]) -> str:
    """A coordinator wake-up as the note its successor reads: what came back, in a line, then what the coordinator
    had asked for and the outcome, as reference data (it can't authorize anything)."""
    from coder.coordinator.wakeups import outcome_summary

    head = PROMPTS.handover_note(outcome_summary(event))
    data = {"source": event["source"], "original_request": (event.get("context") or {}).get("request"),
            "outcome": event.get("payload")}
    return head + _fitting(data, NOTE_CHARS - len(head))
