"""Claude Code: one JSONL per session under ``<home>/projects/<cwd-slug>/``.

Conversation records are ``user`` and ``assistant`` lines forming a tree
through ``uuid``/``parentUuid``; the live conversation is the chain from the
leaf the CLI last recorded (``last-prompt.leafUuid``) back to the root, so
abandoned branches and subagent ``isSidechain`` trees are not the thread.
``message.content`` is a string or a list of blocks — ``text``,
``tool_use``, ``tool_result``, ``thinking``, ``image``. Around the
conversation the CLI writes bookkeeping the thread does not need
(``attachment``, ``queue-operation``, ``last-prompt``, ``mode``,
``bridge-session``, titles, PR links, file-history snapshots, hook
``system`` records) and, after compaction, a ``system`` compact boundary
followed by a user record flagged ``isCompactSummary`` whose text IS the
carried history.

``claude --continue`` resumes the newest session file in the project
directory of its cwd; the slug is the cwd with every non-alphanumeric
character replaced by ``-`` — the cwd as given, not resolved (on macOS the
CLI names ``/Users/…``, never the ``/System/Volumes/Data`` firmlink).
Validated against Claude Code 2.1.261 (read and resume) — see
``tests/test_session_interchange_drift.py``.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter, deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

from ..ir import (
    ASSISTANT, CONTEXT, MESSAGE, OPAQUE, SYSTEM, THINKING, TOOL_CALL, TOOL_RESULT, USER,
    Event, Provenance, StoreRef, TargetIdentity, Thread, count_drops, string, text_of,
)
from .base import InterchangeError, ThreadFormat, Written, pointer_text

CONVERSATION_TYPES = ("user", "assistant")
#: Records the CLI writes beside the conversation; recognised so they land
#: under one drop key instead of reading as something unknown.
BOOKKEEPING_TYPES = frozenset({
    "attachment", "queue-operation", "last-prompt", "atis-latch", "mode", "bridge-session",
    "ai-title", "custom-title", "pr-link", "file-history-snapshot", "file-history-delta", "summary",
})


def project_directory_name(cwd: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(cwd)) or "-"


class ClaudeCodeFormat(ThreadFormat):
    __doc__ = __doc__
    harness = "claude_code"

    # ── locate ──────────────────────────────────────────────────────────────

    def locate(self, store: StoreRef) -> str:
        projects = store.home / "projects"
        wanted = store.session_id or pointer_text(store.pointer)
        if wanted and _is_uuid(wanted):
            hits = list(projects.glob(f"*/{wanted}.jsonl"))
            if not hits:
                raise InterchangeError("source_empty", f"claude session {wanted} not found under {projects}")
            return str(hits[0])
        # The CLI's own rule: newest session in the cwd's project; any project
        # only when that cwd never ran (a moved workdir).
        own = self.newest((projects / project_directory_name(store.cwd)).glob("*.jsonl"))
        found = own or self.newest(projects.glob("*/*.jsonl"))
        if found is None:
            raise InterchangeError("source_empty", f"no claude session under {projects}")
        return str(found)

    # ── read ────────────────────────────────────────────────────────────────

    def read(self, ref: str) -> Thread:
        path = Path(ref)
        records, total, digest = self.read_jsonl(path)
        by_uuid: Dict[str, Tuple[int, dict]] = {}
        meta: Dict[str, Optional[str]] = {"session_id": None, "cwd": None, "version": None, "started_at": None}
        leaf: Optional[str] = None
        last_candidate: Optional[str] = None
        for index, value in records:
            if not isinstance(value, dict):
                continue
            rid = string(value.get("uuid"))
            if rid and rid not in by_uuid:
                by_uuid[rid] = (index, value)
            for key, field_ in (("session_id", "sessionId"), ("cwd", "cwd"), ("version", "version"), ("started_at", "timestamp")):
                meta[key] = meta[key] or string(value.get(field_))
            if value.get("type") == "last-prompt" and string(value.get("leafUuid")):
                leaf = value["leafUuid"]
            if value.get("type") in CONVERSATION_TYPES and isinstance(value.get("message"), dict) \
                    and value.get("isSidechain") is not True and value.get("isMeta") is not True and rid:
                last_candidate = rid
        if not by_uuid or last_candidate is None:
            raise InterchangeError("source_unreadable", f"{path.name} holds no conversation records")
        if leaf not in by_uuid:
            leaf = last_candidate
        chain = self._active_chain(leaf, by_uuid)

        events: List[Event] = []
        model: Optional[str] = None
        for index, value in chain:
            rtype = string(value.get("type")) or "?"
            prov = Provenance(index, rtype)
            ts = string(value.get("timestamp"))
            if rtype == "system":
                reason = "compact_boundary" if value.get("subtype") == "compact_boundary" else f"system_{value.get('subtype') or 'record'}"
                events.append(Event(CONTEXT, prov, role=SYSTEM, timestamp=ts, reason=reason))
                continue
            if rtype not in CONVERSATION_TYPES:
                events.append(Event(OPAQUE, prov, timestamp=ts, reason=f"record_{rtype}"))
                continue
            message = value.get("message") if isinstance(value.get("message"), dict) else {}
            if value.get("isMeta") is True:
                events.append(Event(CONTEXT, prov, role=USER, timestamp=ts, reason="meta"))
                continue
            role = string(message.get("role")) or rtype
            if role not in (USER, ASSISTANT):
                events.append(Event(CONTEXT, prov, role=SYSTEM, timestamp=ts, reason="system_message"))
                continue
            if role == ASSISTANT:
                model = model or string(message.get("model"))
            events.extend(self._events_of(prov, role, message.get("content"), ts, compaction=value.get("isCompactSummary") is True))

        thread = Thread(
            harness=self.harness, source=str(path), session_id=meta["session_id"], cwd=meta["cwd"],
            started_at=meta["started_at"], cli_version=meta["version"], model=model,
            events=events, records=total, sha256=digest,
        )
        thread.dropped = count_drops(events)
        inactive = len(by_uuid) - len(chain)
        if inactive:
            thread.dropped["opaque:inactive_branch_records"] = inactive
        if total > len(records):
            thread.dropped["opaque:unparseable_lines"] = total - len(records)
        return thread

    @staticmethod
    def _active_chain(leaf: str, by_uuid: Dict[str, Tuple[int, dict]]) -> List[Tuple[int, dict]]:
        chain: List[Tuple[int, dict]] = []
        seen: set = set()
        cursor: Optional[str] = leaf
        while cursor:
            if cursor in seen:
                raise InterchangeError("source_unreadable", "claude record ancestry contains a cycle")
            seen.add(cursor)
            entry = by_uuid.get(cursor)
            if entry is None:
                raise InterchangeError("source_unreadable", f"claude record ancestry references missing uuid {cursor}")
            chain.append(entry)
            value = entry[1]
            # A compact boundary has no parent: what came before was
            # compacted, and the summary that follows the boundary carries it.
            cursor = string(value.get("parentUuid"))
        chain.reverse()
        return chain

    @staticmethod
    def _events_of(prov: Provenance, role: str, content: Any, ts: Optional[str], *, compaction: bool) -> List[Event]:
        reason = "summary" if compaction else ""
        if isinstance(content, str):
            if not content:
                return []
            e = Event(MESSAGE, prov, role=role, text=content, timestamp=ts)
            return [e] if not compaction else [Event(MESSAGE, prov, role=USER, text=content, timestamp=ts, reason=reason)]
        if not isinstance(content, list):
            return [Event(OPAQUE, prov, role=role, timestamp=ts, reason="unsupported_message_content")]
        out: List[Event] = []
        for i, block in enumerate(content):
            p = Provenance(prov.record, prov.record_type, i)
            if not isinstance(block, dict):
                out.append(Event(OPAQUE, p, role=role, timestamp=ts, reason="block_not_object"))
                continue
            btype = string(block.get("type")) or "?"
            if btype == "text":
                if string(block.get("text")):
                    out.append(Event(MESSAGE, p, role=role, text=block["text"], timestamp=ts, reason=reason))
            elif btype == "tool_use":
                out.append(Event(TOOL_CALL, p, role=ASSISTANT, timestamp=ts, tool_name=string(block.get("name")),
                                 tool_call_id=string(block.get("id")), tool_input=block.get("input", {})))
            elif btype == "tool_result":
                out.append(Event(TOOL_RESULT, p, timestamp=ts, tool_call_id=string(block.get("tool_use_id")),
                                 text=text_of(block.get("content")), is_error=block.get("is_error") is True))
                if isinstance(block.get("content"), list) and any(isinstance(b, dict) and b.get("type") == "image" for b in block["content"]):
                    out.append(Event(CONTEXT, p, role=USER, timestamp=ts, reason="tool_result_image"))
            elif btype in ("thinking", "redacted_thinking"):
                out.append(Event(THINKING, p, role=ASSISTANT, timestamp=ts))
            elif btype in ("image", "document"):
                out.append(Event(CONTEXT, p, role=role, timestamp=ts, reason=btype))
            else:
                out.append(Event(OPAQUE, p, role=role, timestamp=ts, reason=f"block_{btype}"))
        return out

    # ── write ───────────────────────────────────────────────────────────────

    def write(self, thread: Thread, store: StoreRef, identity: TargetIdentity) -> Written:
        session_id = self.new_session_id()
        path = store.home / "projects" / project_directory_name(store.cwd) / f"{session_id}.jsonl"
        fallback_ts = thread.started_at or self.now()
        model = identity.model or thread.model or "unknown"
        records: List[Dict[str, Any]] = []
        dropped: Counter = Counter()
        parent: Optional[str] = None
        seen_calls: set = set()
        generated: Deque[str] = deque()
        counter = 0

        def emit(rtype: str, message: Dict[str, Any], ts: Optional[str]) -> None:
            nonlocal parent
            rid = str(uuid.uuid4())
            record: Dict[str, Any] = {
                "parentUuid": parent, "isSidechain": False, "userType": "external", "cwd": str(store.cwd),
                "sessionId": session_id, "version": identity.cli_version or thread.cli_version or "", "gitBranch": "",
                "uuid": rid, "timestamp": ts or fallback_ts, "type": rtype, "message": message,
            }
            if rtype == "assistant":
                record["requestId"] = f"req_nc_{uuid.uuid4().hex}"
            records.append(record)
            parent = rid

        def assistant(blocks: List[Dict[str, Any]], ts: Optional[str]) -> None:
            emit("assistant", {
                "id": f"msg_nc_{uuid.uuid4().hex}", "type": "message", "role": "assistant", "model": model,
                "content": blocks, "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0},
            }, ts)

        for event in thread.events:
            if event.is_turn:
                if event.role == USER:
                    emit("user", {"role": "user", "content": event.text}, event.timestamp)
                else:
                    assistant([{"type": "text", "text": event.text}], event.timestamp)
            elif event.kind == TOOL_CALL:
                call_id = event.tool_call_id
                if not call_id:
                    counter += 1
                    call_id = f"toolu_nc_{counter:04d}"
                    generated.append(call_id)
                    dropped["tool_call:missing_id"] += 1
                tool_input = event.tool_input
                if not isinstance(tool_input, dict):
                    tool_input = {"input": tool_input if tool_input is not None else ""}
                    dropped["tool_call:non_object_input"] += 1
                seen_calls.add(call_id)
                assistant([{"type": "tool_use", "id": call_id, "name": event.tool_name or "unknown_tool", "input": tool_input}], event.timestamp)
                if not event.tool_name:
                    dropped["tool_call:missing_name"] += 1
            elif event.kind == TOOL_RESULT:
                call_id = event.tool_call_id
                if not call_id:
                    call_id = generated.popleft() if generated else ""
                    if not call_id:
                        dropped["tool_result:orphan_id"] += 1
                        continue
                elif call_id not in seen_calls:
                    dropped["tool_result:orphan_id"] += 1
                    continue
                emit("user", {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": call_id, "content": event.text or "", "is_error": bool(event.is_error)},
                ]}, event.timestamp)
            else:
                dropped[event.drop_key] += 1
        return Written(session_id=session_id, native_path=path, records=records, dropped=dropped)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False
