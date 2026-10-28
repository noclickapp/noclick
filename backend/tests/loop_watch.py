"""How long the event loop stopped answering while an awaitable ran.

A sync call on the loop (a network round trip, a sleep, a big parse) freezes
every request on the container at once; a test of such a path awaits it here and
bounds the longest gap between the ticks of a 10ms ticker.
"""

import asyncio
import time
from typing import Any, Awaitable, Tuple


async def longest_loop_gap(awaitable: Awaitable[Any], tick: float = 0.01) -> Tuple[Any, float]:
    """(the awaitable's result, the longest seconds the loop went without a tick while it ran)."""
    longest = 0.0
    done = asyncio.Event()

    async def ticker() -> None:
        nonlocal longest
        last = time.monotonic()
        while not done.is_set():
            await asyncio.sleep(tick)
            now = time.monotonic()
            longest = max(longest, now - last)
            last = now

    beat = asyncio.create_task(ticker())
    await asyncio.sleep(tick)
    try:
        result = await awaitable
    finally:
        done.set()
        await beat
    return result, longest
