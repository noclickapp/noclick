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
``TURN_LIMITS_KEY`` is how far a turn goes (``{steps, usd, minutes}``, each
left out at the engine's default), and ``TURN_WRAP_UP_KEY`` what a turn one of
those limits ended is told, for one more call without tools that says where its
work stands, with the line a person reads after it (``{steps|spend|time:
{prompt, line}}``); given ``funds``, a tool the credit gate turns down ends the
turn too, which says what it got done and fails on the gate's words.
``TURN_SO_FAR_KEY`` is how far the turn had gone before this run of it
(``{started_at, steps, usd, quiet}``), when a platform runs on a turn another process
started: the run meets those limits from there.
``TURN_FIRST_EFFORT_KEY`` is the reasoning effort of a turn's first model call,
for one someone waits on: its first words come sooner. ``TURN_EMPTY_ANSWER_KEY``
is what a turn whose model answered with nothing (no words, no call) is told,
once, to run on rather than end there. ``TURN_COMMAND_KEY`` makes the turn one of
its harness's own commands (``{name, arguments}``) rather than a message: it's
delivered as that command alone, with none of what a message carries composed in,
and kept on its persisted message as ``command``. ``TURN_PERMISSION_MODE_KEY`` is the conversation's permission
mode for a coding harness (``approval-required``, ``auto-accept-edits``, ``auto``, ``full-access``), delivered with
its message: a person answers what the harness asks. ``TURN_EFFORT_KEY`` and ``TURN_SPEED_KEY`` are how hard and how
fast the turn's model works (the conversation's, else its agent's)."""

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
TURN_LIMITS_KEY = "_turnLimits"
TURN_SO_FAR_KEY = "_turnSoFar"
TURN_FIRST_EFFORT_KEY = "_turnFirstEffort"
TURN_EMPTY_ANSWER_KEY = "_turnEmptyAnswer"
TURN_COMMAND_KEY = "_turnCommand"
TURN_PERMISSION_MODE_KEY = "_turnPermissionMode"
TURN_EFFORT_KEY = "_turnEffort"
TURN_SPEED_KEY = "_turnSpeed"
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


def turn_wrap_up_of(node_config: Any) -> Optional[Dict[str, Any]]:
    """What a turn a limit ended is told for its last, tool-less call, by limit; None: it ends on the limit's line."""
    value = node_config.get(TURN_WRAP_UP_KEY) if isinstance(node_config, dict) else None
    return value if isinstance(value, dict) and value else None


def turn_limits_of(node_config: Any) -> Optional[Dict[str, Any]]:
    """The limits a platform set for the turn, when it set any."""
    value = node_config.get(TURN_LIMITS_KEY) if isinstance(node_config, dict) else None
    return value if isinstance(value, dict) and value else None


def turn_so_far_of(node_config: Any) -> Optional[Dict[str, Any]]:
    """How far the turn had gone before this run of it, when a platform said."""
    value = node_config.get(TURN_SO_FAR_KEY) if isinstance(node_config, dict) else None
    return value if isinstance(value, dict) and value else None


def turn_first_effort_of(node_config: Any) -> Optional[str]:
    """The reasoning effort of the turn's first model call, when a platform set one."""
    return _text(node_config, TURN_FIRST_EFFORT_KEY)


def turn_empty_answer_of(node_config: Any) -> Optional[str]:
    """What the turn is told when its model answers with nothing, when a platform set it."""
    return _text(node_config, TURN_EMPTY_ANSWER_KEY)


def turn_command_of(node_config: Any) -> Optional[Dict[str, str]]:
    """The harness command a turn runs (``{name, arguments}``), when a platform made the turn one."""
    value = node_config.get(TURN_COMMAND_KEY) if isinstance(node_config, dict) else None
    if not isinstance(value, dict) or not isinstance(value.get("name"), str) or not value["name"]:
        return None
    arguments = value.get("arguments")
    return {"name": value["name"], "arguments": arguments if isinstance(arguments, str) else ""}


def turn_permission_mode_of(node_config: Any) -> Optional[str]:
    """The conversation's permission mode, when a platform bound one (a person answers what the harness asks)."""
    return _text(node_config, TURN_PERMISSION_MODE_KEY)


def turn_effort_of(node_config: Any) -> Optional[str]:
    """The reasoning effort the turn's model calls run at, when a platform set one (its harness's own word)."""
    return _text(node_config, TURN_EFFORT_KEY)


def turn_speed_of(node_config: Any) -> Optional[str]:
    """``fast`` when a platform runs the turn in its harness's fast mode."""
    return _text(node_config, TURN_SPEED_KEY)


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
