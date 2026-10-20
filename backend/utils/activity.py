"""Tell whoever runs this instance what its users did, for the activity feed it
keeps (the ``ACTIVITY_SIGNAL`` capability). Without one, nothing happens.

Each action is reported once, where every surface of it meets (a credential
saved, a workflow created, a number bought), as a name the feed knows and the
facts it reads: never a secret, never more than the line needs. A feed that
fails never fails the action it reports."""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Union

from utils.capabilities import ACTIVITY_SIGNAL, capability

logger = logging.getLogger(__name__)

# Who a build is for, by its request's ``source`` (absent: the person, in the builder's chat).
_BUILT_BY = {"coordinator": "coordinator", "platform_api": "api", "agent_prompt_builder": "agent"}


def signal_activity(user: Union[str, Mapping[str, Any]], action: str, details: Optional[Mapping[str, Any]] = None,
                    *, key: Optional[str] = None) -> None:
    """``user`` did ``action`` (``details``: its facts). Records with the same ``key`` in a row are one line
    in the feed. Fire-and-forget."""
    record = capability(ACTIVITY_SIGNAL)
    if record is None:
        return
    try:
        record(user, action, dict(details or {}), key=key)
    except Exception:
        logger.warning("activity_signal_failed action=%s", action, exc_info=True)


def built_by(context: Mapping[str, Any]) -> str:
    """Who a build, or a workflow it makes, is for, as the feed says it: ``by`` where whoever started it said
    (the platform API, for the account's coordinator), else its ``source``: the builder's chat, the
    coordinator, the API or an agent."""
    return context.get("by") or _BUILT_BY.get(context.get("source") or "", "builder")
