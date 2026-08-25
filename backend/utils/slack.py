"""No-op compatibility surface for managed operator notifications.

Community workflows can still use the ordinary Slack integration node. These
helpers are separate: they are hooks used by the managed service's own team
notifications and deliberately do not transmit community user activity.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def _is_configured() -> bool:
    return False


def login_notifications_enabled() -> bool:
    return False


def get_posthog_user_url(user_email: str) -> None:
    del user_email
    return None


def _normalize_channel(channel: Optional[str]) -> Optional[str]:
    if not channel:
        return None
    if channel[0] in ("C", "G", "D") or channel.startswith("#"):
        return channel
    return f"#{channel}"


def extract_user_name(user_data: Dict[str, Any]) -> str:
    metadata = user_data.get("user_metadata", {})
    return (
        metadata.get("full_name")
        or metadata.get("name")
        or user_data.get("email", "").split("@")[0]
        or "Unknown"
    )


async def send_slack_message(*args, **kwargs) -> None:
    return None


async def send_activity_notification(*args, **kwargs) -> None:
    return None


async def update_slack_message(*args, **kwargs) -> bool:
    return False


async def mark_session_complete(*args, **kwargs) -> bool:
    return False


def send_activity_notification_background(*args, **kwargs) -> None:
    return None


def send_to_channel_background(*args, **kwargs) -> None:
    return None


def compute_workflow_delta(*args, **kwargs) -> None:
    return None


def send_workflow_update_notification_background(*args, **kwargs) -> None:
    return None


async def send_login_notification(*args, **kwargs) -> None:
    return None
