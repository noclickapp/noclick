"""Helpers for tests that must observe fire-and-forget work."""

import asyncio


async def drain_spawned_tasks():
    """Await fire-and-forget tasks (utils.async_helpers.spawn) so their effects
    are observable before asserting.

    Only drains tasks bound to the CURRENT loop: `_bg_tasks` is process-global,
    so under a full-suite run it can hold leftovers from earlier tests' dead
    per-test loops — gathering those raises "future belongs to a different
    loop" and they can never complete anyway.
    """
    from utils.async_helpers import _bg_tasks

    loop = asyncio.get_running_loop()
    while True:
        mine = [t for t in _bg_tasks if t.get_loop() is loop and not t.done()]
        if not mine:
            break
        await asyncio.gather(*mine, return_exceptions=True)
