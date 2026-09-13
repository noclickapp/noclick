"""The harness-independent shape of a conversation thread.

A harness's session store holds a great deal that is its own business —
token accounting, hook output, UI projections, reasoning the provider bound
to its own model. What another harness needs to CONTINUE the conversation is
narrower: the messages, in order, and every tool call paired with its
result. That is the ``Thread`` here. Everything a reader cannot carry is not
discarded silently: it becomes an event of kind ``OPAQUE``/``CONTEXT``/
``THINKING`` with a reason, so the manifest says what a move left behind
and the verdict can tell an accepted loss from a structural one.

Every event carries its ``Provenance`` (record index, record type, block
index in the source store), so a failed verdict names the line to look at.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

#: Bumped whenever a writer's output changes shape. Recorded in every
#: manifest and verdict so a store can be traced to the code that wrote it.
INTERCHANGE_VERSION = "1"

# ── event kinds ──────────────────────────────────────────────────────────────
MESSAGE = "message"          # a user or assistant turn (role + text)
TOOL_CALL = "tool_call"      # the assistant invoking a tool (name, id, input)
TOOL_RESULT = "tool_result"  # the tool's answer (id, text, is_error)
THINKING = "thinking"        # provider-bound reasoning; never crosses harnesses
CONTEXT = "context"          # harness-injected context (system prompts, environment notes, images)
OPAQUE = "opaque"            # a record or block the reader recognises as bookkeeping, or does not recognise at all

USER = "user"
ASSISTANT = "assistant"
SYSTEM = "system"

#: Drop counters a move may carry without failing: the bookkeeping the
#: source harness keeps for itself, reasoning bound to its provider,
#: context the target harness injects for itself, and shapes a writer
#: represents differently but losslessly. Any other counter — an orphaned
#: tool result, unsupported message content — is structural, and fails the
#: verdict. Counter keys are ``<kind>:<reason>``; a prefix here matches its
#: whole family.
ACCEPTED_DROP_PREFIXES: Tuple[str, ...] = (
    "opaque:",
    "thinking",
    "context:",
    "compaction:",                 # the source compacted its own history; the summary is carried as a message
    "tool_call:non_object_input",  # a string input is wrapped as {"input": …}
    "tool_call:missing_id",        # a generated id pairs the result by position
)


@dataclass(frozen=True)
class Provenance:
    """Where an event came from in the source store."""

    record: int
    record_type: str = ""
    block: Optional[int] = None

    def __str__(self) -> str:
        where = f"record {self.record}"
        if self.record_type:
            where += f" ({self.record_type})"
        if self.block is not None:
            where += f" block {self.block}"
        return where


@dataclass
class Event:
    kind: str
    provenance: Provenance
    role: Optional[str] = None
    text: Optional[str] = None
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_input: Any = None
    is_error: bool = False
    timestamp: Optional[str] = None
    reason: str = ""  # for OPAQUE/CONTEXT/THINKING: the drop counter this event will land in

    @property
    def is_turn(self) -> bool:
        return self.kind == MESSAGE and self.role in (USER, ASSISTANT) and bool(self.text)

    @property
    def drop_key(self) -> str:
        return f"{self.kind}:{self.reason}" if self.reason else self.kind


@dataclass
class Thread:
    harness: str
    source: str
    session_id: Optional[str]
    cwd: Optional[str]
    started_at: Optional[str]
    cli_version: Optional[str]
    model: Optional[str]
    events: List[Event]
    records: int
    sha256: Optional[str] = None
    #: What the reader could not carry into events, by drop key — the
    #: source harness's own bookkeeping mostly, listed so the manifest is honest.
    dropped: Counter = field(default_factory=Counter)

    def summary(self) -> Dict[str, Any]:
        kinds = Counter(e.kind for e in self.events)
        return {
            "harness": self.harness, "source": self.source, "session_id": self.session_id, "cwd": self.cwd,
            "started_at": self.started_at, "cli_version": self.cli_version, "model": self.model,
            "records": self.records, "events": dict(kinds), "dropped": dict(self.dropped), "sha256": self.sha256,
        }


@dataclass
class Skeleton:
    """What a faithful translation must preserve: every user/assistant
    message with its text, every tool call paired with its result, in order.
    Ids are deliberately not part of it — a writer may mint one for a call
    that had none — but names, texts and pairing are."""

    roles: List[str]
    digest: str
    tool_calls: int
    tool_results: int
    unpaired_tool_calls: int

    @property
    def messages(self) -> int:
        return len(self.roles)

    def as_dict(self) -> Dict[str, Any]:
        return {"messages": self.messages, "tool_calls": self.tool_calls, "tool_results": self.tool_results,
                "unpaired_tool_calls": self.unpaired_tool_calls, "digest": self.digest[:16]}


def skeleton_of(thread: Thread) -> Skeleton:
    roles: List[str] = []
    material: List[Any] = []
    calls = results = 0
    open_calls: set = set()
    for event in thread.events:
        if event.is_turn:
            roles.append(event.role)  # type: ignore[arg-type]
            material.append([event.role, event.text])
        elif event.kind == TOOL_CALL:
            calls += 1
            material.append(["call", event.tool_name or ""])
            if event.tool_call_id:
                open_calls.add(event.tool_call_id)
        elif event.kind == TOOL_RESULT:
            results += 1
            material.append(["result", event.text or ""])
            open_calls.discard(event.tool_call_id)
    digest = hashlib.sha256(json.dumps(material, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return Skeleton(roles=roles, digest=digest, tool_calls=calls, tool_results=results, unpaired_tool_calls=len(open_calls))


def classify_drops(dropped: Dict[str, int]) -> Dict[str, int]:
    """The drop counters a move may NOT carry — non-empty fails the verdict."""
    return {
        key: count for key, count in dropped.items()
        if count and not any(key == p.rstrip(":") or key.startswith(p) for p in ACCEPTED_DROP_PREFIXES)
    }


@dataclass
class StoreRef:
    """Where one harness keeps this conversation's thread, and how the harness
    finds it again. ``home`` is the directory the format addresses (the
    Claude config dir, ``CODEX_HOME``), ``cwd`` the working directory the
    thread ran under (Claude keys sessions on it), ``pointer`` the file
    NoClick's runner reads to resume by id (codex's thread file; the local
    Claude runner's continue marker). A move writes the new thread's id
    into the target's pointer."""

    harness: str
    home: Path
    cwd: Path
    pointer: Optional[Path] = None
    session_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"harness": self.harness, "home": str(self.home), "cwd": str(self.cwd),
                "pointer": str(self.pointer) if self.pointer else None, "session_id": self.session_id}


@dataclass
class TargetIdentity:
    """What the target harness runs as: recorded in the written store's
    header so a resume behaves like the harness's own sessions. Each field
    matters to some harness — Codex calls the provider its rollout header
    names over the configured one."""

    cli_version: Optional[str] = None
    model_provider: Optional[str] = None
    model: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"cli_version": self.cli_version, "model_provider": self.model_provider, "model": self.model}


def text_of(content: Any) -> str:
    """The text a tool result or message content carries, whatever shape
    the harness gave it: a string, or a list of blocks with ``text``."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(p for p in parts if p)
    return ""


def string(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def count_drops(events: Iterable[Event]) -> Counter:
    return Counter(e.drop_key for e in events if e.kind in (OPAQUE, CONTEXT, THINKING))
