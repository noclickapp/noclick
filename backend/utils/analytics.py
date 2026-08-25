"""Compatibility no-ops for optional installation analytics.

The community runtime does not collect product events or join browser activity
to a third-party replay service. Call sites remain harmless so shared workflow
logic does not need analytics conditionals.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Dict, Optional


def log_activity(
    event_name: str,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> None:
    return None


async def log_activity_async(
    event_name: str,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> None:
    return None


def log_activity_background(
    event_name: str,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> None:
    return None


def set_person_properties(
    user_id: Optional[str], properties: Dict[str, Any], set_once: bool = False
) -> None:
    return None


async def set_person_properties_async(
    user_id: Optional[str], properties: Dict[str, Any], set_once: bool = False
) -> None:
    return None


def set_person_properties_background(
    user_id: Optional[str], properties: Dict[str, Any], set_once: bool = False
) -> None:
    return None


def track_event(event_name: str):
    """Preserve decorated call behavior without collecting an event."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        import inspect

        return async_wrapper if inspect.iscoroutinefunction(func) else wrapper

    return decorator


def shutdown() -> None:
    return None
