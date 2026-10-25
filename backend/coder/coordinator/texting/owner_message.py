"""How the assistant reaches its owner's phone outside a reply (``message_owner``, a reminder, a finished job): over
the app they last texted on, unless the caller names one. A platform with its own sender registers it as
``OWNER_MESSAGE``; otherwise this instance's own lines send it. The result says whether it went (``success``,
``message_id``), else why not (``error``) and whether trying again could help (``permanent``)."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from coder.coordinator.reach import last_phone_app
from utils.capabilities import OWNER_MESSAGE, capability
from utils.sendblue import line_number
from utils.whatsapp_cloud_api import display_number

LINES = {"whatsapp": display_number, "imessage": line_number}


async def send_owner_message(pool, user_id: str, text: str, *, link: Optional[str] = None,
                             channel: Optional[str] = None, share_profile: bool = False,
                             typing: bool = False) -> Dict[str, Any]:
    """``share_profile`` and ``typing`` are iMessage's (``imessage.send_owner_imessage``)."""
    from coder.coordinator.texting.imessage import send_owner_imessage
    from coder.coordinator.texting.whatsapp import send_owner_whatsapp

    app = channel or await last_phone_app(pool, user_id) or next((a for a, line in LINES.items() if line()), None)
    if app == "imessage":
        return await send_owner_imessage(pool, user_id, text, link=link, share_profile=share_profile, typing=typing)
    return await send_owner_whatsapp(pool, user_id, text, link=link)


def phone_sender(app: Optional[str] = None) -> Optional[Callable[..., Any]]:
    """What sends to the owner's phone over ``app`` ("whatsapp" | "imessage"; None for any): the platform's sender,
    else this instance's when it has a line for that app; None when nothing can."""
    registered = capability(OWNER_MESSAGE)
    if registered is not None:
        return registered
    lines = [LINES[app]] if app else LINES.values()
    return send_owner_message if any(line() for line in lines) else None
