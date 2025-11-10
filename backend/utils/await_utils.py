"""
Asyncio utility functions for event loop management.
"""

import asyncio


def get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """
    Get the current event loop or create a new one if none exists.

    This is useful for code that may be called from both async and sync contexts.

    Returns:
        The current event loop or a newly created one.
    """
    try:
        # Try to get the running event loop
        return asyncio.get_running_loop()
    except RuntimeError:
        # No running loop, try to get the current event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                # Loop is closed, create a new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            return loop
        except RuntimeError:
            # No event loop at all, create a new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop
