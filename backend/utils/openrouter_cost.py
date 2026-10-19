"""What an OpenRouter call cost, when its response didn't say.

A call's cost normally rides back in the response (``usage.cost``, read by
``coder.openai_agent.litellm_model.extract_cost_from_response``). When it
doesn't (a dropped usage chunk, a model priced nowhere else), OpenRouter's own
record of the generation has it: ``/api/v1/generation`` answers a few seconds
after the call (404 until then). A missing cost is priced from that record,
and one that can't be is raised as ``CostUnknown`` for the caller to log
loudly: never charged as $0, never guessed.
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from typing import Any, Optional

import httpx

GENERATION_URL = "https://openrouter.ai/api/v1/generation"
# The record is usually there within ten seconds of the call; this rides out a slow write.
LOOKUP_DEADLINE_S = 60.0
_FIRST_WAIT_S = 2.0
_MAX_WAIT_S = 10.0


class CostUnknown(RuntimeError):
    """A call's cost is in neither its response nor OpenRouter's record of it."""


def generation_id_of(*objects: Any) -> Optional[str]:
    """OpenRouter's id for the generation (``gen-…``) on a response (or its
    JSON) or any of its stream chunks: its own id, or where litellm keeps it."""
    for obj in objects:
        if obj is None:
            continue
        own = obj.get("id") if isinstance(obj, dict) else getattr(obj, "id", None)
        hidden = getattr(obj, "_hidden_params", None)
        hidden = hidden if isinstance(hidden, dict) else {}
        for value in (own, hidden.get("received_model_id"), hidden.get("id")):
            if isinstance(value, str) and value.startswith("gen-"):
                return value
    return None


async def generation_cost(generation_id: str) -> Decimal:
    """What OpenRouter charged for ``generation_id`` (its ``total_cost``, in
    dollars), asked with backoff until ``LOOKUP_DEADLINE_S`` while the record is
    written or the endpoint is down. Raises ``CostUnknown``."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise CostUnknown(f"no OPENROUTER_API_KEY to look up {generation_id}")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + LOOKUP_DEADLINE_S
    wait, last = _FIRST_WAIT_S, "no answer"
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                response = await client.get(GENERATION_URL, params={"id": generation_id},
                                            headers={"Authorization": f"Bearer {api_key}"})
                if response.status_code == 200:
                    cost = ((response.json() or {}).get("data") or {}).get("total_cost")
                    if cost is not None:
                        return Decimal(str(cost))
                    last = "a record without total_cost"
                else:
                    last = f"HTTP {response.status_code}"
            except (httpx.HTTPError, ValueError) as exc:
                last = f"{type(exc).__name__}: {exc}"
            if loop.time() + wait > deadline:
                raise CostUnknown(f"OpenRouter has no cost for {generation_id} after {LOOKUP_DEADLINE_S:.0f}s ({last})")
            await asyncio.sleep(wait)
            wait = min(wait * 2, _MAX_WAIT_S)


async def settle(cost: Optional[float], reported: bool, generation_id: Optional[str]) -> Decimal:
    """A call's vendor cost: the one its response reported, else OpenRouter's
    record of its generation. Raises ``CostUnknown`` when neither has it. An
    instance that bills nobody (``billing.usage_tracker.charges_usage``)
    records an unreported cost as $0 without asking: nothing is charged."""
    from billing.usage_tracker import charges_usage

    if reported:
        return Decimal(str(cost or 0))
    if not charges_usage():
        return Decimal(0)
    if not generation_id:
        raise CostUnknown("the response reported no cost and named no generation to look it up by")
    return await generation_cost(generation_id)
