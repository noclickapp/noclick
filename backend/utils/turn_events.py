"""An agent turn as it happens, for whatever watches it (``TURN_EVENTS``).

Each runtime hands its moments to ``publish`` with the conversation id the turn
runs under: the reply's text as it is written, each tool call as it is about to
run (or is held), and each tool result. A platform that names its turns sets the
runtime config key ``TURN_REF_KEY`` on the agent node; the conversation events
that turn persists carry it as ``turn``, so a watcher can tell its own turns'
messages apart."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from utils.capabilities import TURN_EVENTS, capability

logger = logging.getLogger(__name__)

TURN_REF_KEY = "_turnRef"


def turn_ref_of(node_config: Any) -> Optional[str]:
    """The id a platform gave the turn, when it gave one."""
    ref = node_config.get(TURN_REF_KEY) if isinstance(node_config, dict) else None
    return ref if isinstance(ref, str) and ref else None


def publish(conversation_id: Optional[str], event: Dict[str, Any]) -> None:
    """Hand one moment of a turn to the watcher, if any. Never raises: watching
    a turn must never fail it."""
    sink = capability(TURN_EVENTS)
    if sink is None or not conversation_id:
        return
    try:
        sink(conversation_id, event)
    except Exception:
        logger.exception("[turn_events] publishing a %s event failed", event.get("type"))
