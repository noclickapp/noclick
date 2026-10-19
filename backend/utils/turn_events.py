"""An agent turn as it happens, for whatever watches it (``TURN_EVENTS``).

Each runtime hands its moments to ``publish`` with the conversation id the turn
runs under: the reply's text as it is written, each tool call as it is about to
run (or is held), each tool result, and each file the turn makes (``made_file``), which
the turn collecting them (``files_made``) also keeps with its reply.
A platform may add moments of its own. A platform that names its turns sets the
runtime config key ``TURN_REF_KEY`` on the agent node; the conversation events
that turn persists carry it as ``turn``, so a watcher can tell its own turns'
messages apart. ``TURN_VIA_KEY`` says how the turn's message arrived (``whatsapp``,
``imessage``, ``call``, ``email``), kept on its persisted message as ``via``;
``TURN_NOTE_KEY`` is a line for the model only (how to answer on that app, what
the email's headers were), put ahead of the message after it's persisted.
``TURN_TRIGGER_KEY`` says what started a turn no person sent (a trigger's event,
a schedule, a wake-up), merged into its persisted message's ``trigger``.
``TURN_WRAP_UP_KEY`` is what a turn that has made every model call it may is
told, for one more call without tools that says where its work stands."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, List, Optional

from utils.capabilities import TURN_EVENTS, capability

logger = logging.getLogger(__name__)

TURN_REF_KEY = "_turnRef"
TURN_VIA_KEY = "_turnVia"
TURN_NOTE_KEY = "_turnNote"
TURN_TRIGGER_KEY = "_turnTrigger"
TURN_WRAP_UP_KEY = "_turnWrapUp"
# What a person reads when a turn fails: the error's own words stay in the log and the turn's record.
TURN_FAILED_LINE = "Sorry, I hit a problem on my side. Please try that again in a moment."

_files_made: ContextVar[Optional[List[Dict[str, Any]]]] = ContextVar("turn_files_made", default=None)


def _text(node_config: Any, key: str) -> Optional[str]:
    value = node_config.get(key) if isinstance(node_config, dict) else None
    return value if isinstance(value, str) and value else None


def turn_ref_of(node_config: Any) -> Optional[str]:
    """The id a platform gave the turn, when it gave one."""
    return _text(node_config, TURN_REF_KEY)


def turn_via_of(node_config: Any) -> Optional[str]:
    """How the turn's message arrived, when a platform said."""
    return _text(node_config, TURN_VIA_KEY)


def turn_note_of(node_config: Any) -> Optional[str]:
    """The line the model reads ahead of the turn's message, never persisted."""
    return _text(node_config, TURN_NOTE_KEY)


def turn_wrap_up_of(node_config: Any) -> Optional[str]:
    """What a turn out of model calls is told for its last, tool-less one; None: it fails there."""
    return _text(node_config, TURN_WRAP_UP_KEY)


def turn_trigger_of(node_config: Any) -> Optional[Dict[str, Any]]:
    """What started a turn no person sent, when a platform said."""
    value = node_config.get(TURN_TRIGGER_KEY) if isinstance(node_config, dict) else None
    return value if isinstance(value, dict) and value else None


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


@contextmanager
def files_made() -> Iterator[List[Dict[str, Any]]]:
    """The files the turn running in this context makes (``made_file``), as it makes them."""
    files: List[Dict[str, Any]] = []
    token = _files_made.set(files)
    try:
        yield files
    finally:
        _files_made.reset(token)


def made_file(conversation_id: Optional[str], file: Dict[str, Any]) -> None:
    """A file the turn made (``{name, url, mime_type, size_bytes}``): kept by the
    turn collecting its files and handed to whatever watches it."""
    collecting = _files_made.get()
    if collecting is not None:
        collecting.append(file)
    publish(conversation_id, {"type": "file", "role": "assistant", "file": file})
