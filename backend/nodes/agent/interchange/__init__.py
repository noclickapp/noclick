"""Conversation threads move between harnesses as the harness's own session
files, never as a history dump in the first message.

Each CLI harness keeps a conversation in its native store, and that store
is the full-fidelity record of the thread: roles, tool calls with their
results, timestamps. Loading a thread NATIVELY keeps that structure, so the
provider's prefix caching and the harness's own compaction keep working
turn over turn. This package turns one harness's store into another's:

- ``ir``        — the harness-independent ``Thread``, its skeleton, the drop vocabulary
- ``formats``   — one ``ThreadFormat`` per harness (``claude_code``, ``codex``), in a registry
- ``engine``    — ``read_thread`` / ``translate`` / ``move_thread`` with the read-back verdict and manifests
- ``fallback``  — the carried-context block for a thread that could not move
- ``__main__``  — ``move`` / ``inspect`` / ``formats`` commands (what runs inside a sandbox)

The package is stdlib-only and imports nothing from the backend: it is
shipped into the hosted sandboxes as files and run there, and runs
in-process in the local edition. NoClick's side of it — which harness a
conversation row names, version pins, reporting — lives in
``nodes/agent/session_interchange.py``.
"""

from .engine import Fidelity, InterchangeResult, inspect_store, move_thread, parse_verdict, read_thread, translate
from .fallback import carried_context, turns_from_projection, with_carried_context
from .formats import FORMATS, REASONS, InterchangeError, ThreadFormat, describe_formats, format_for
from .ir import (
    ACCEPTED_DROP_PREFIXES, INTERCHANGE_VERSION, Event, Provenance, Skeleton, StoreRef, TargetIdentity, Thread,
    classify_drops, skeleton_of,
)

__all__ = [
    "ACCEPTED_DROP_PREFIXES", "Event", "FORMATS", "Fidelity", "INTERCHANGE_VERSION", "InterchangeError",
    "InterchangeResult", "Provenance", "REASONS", "Skeleton", "StoreRef", "TargetIdentity", "Thread", "ThreadFormat",
    "carried_context", "classify_drops", "describe_formats", "format_for", "inspect_store", "move_thread",
    "parse_verdict", "read_thread", "skeleton_of", "translate", "turns_from_projection", "with_carried_context",
]
