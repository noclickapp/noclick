"""Codex: one rollout JSONL per thread under ``<home>/sessions/YYYY/MM/DD/``.

Every line is ``{timestamp, type, payload}``. ``session_meta`` opens the
file (ids, cwd, ``cli_version``, ``model_provider``, ``history_mode``); the
conversation the model sees is the ``response_item`` stream — ``message``
(role user/assistant, and ``developer``/``system`` for the harness's own
instructions), ``function_call``/``custom_tool_call`` with their
``*_output``, ``reasoning`` (encrypted, provider-bound). ``event_msg`` lines
mirror it for the UI (``user_message``, ``agent_message``, task and token
events); ``turn_context``, ``world_state`` and ``token_usage_record`` are
per-turn bookkeeping. After a window compaction a ``compacted`` record's
``replacement_history`` is the history the model continues from. Codex
injects context into the user role itself (``<environment_context>``,
``<user_instructions>`` …); those are the harness's, not the thread's.

The app-server resumes a thread by id (``thread/resume``) from the rollout
whose filename ends in that id, and it calls the provider the rollout
header names over the configured one — a moved thread must name the
target's. Validated against Codex 0.153.4 (read and resume) — see
``tests/test_session_interchange_drift.py``.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..ir import (
    ASSISTANT, CONTEXT, MESSAGE, OPAQUE, SYSTEM, THINKING, TOOL_CALL, TOOL_RESULT, USER,
    Event, Provenance, StoreRef, TargetIdentity, Thread, count_drops, string, text_of,
)
from .base import InterchangeError, ThreadFormat, Written

#: A user-role message that is really the harness talking to the model:
#: one tag wrapping the whole text.
_INJECTED = re.compile(r"^\s*<([a-z_]+)>[\s\S]*</\1>\s*$")
_THREAD_ID = re.compile(r"rollout-.*-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$")


def rollout_relative_path(session_id: str, started_at: str) -> Path:
    stamp = _parse_ts(started_at)
    return Path("sessions") / stamp.strftime("%Y") / stamp.strftime("%m") / stamp.strftime("%d") / f"rollout-{stamp.strftime('%Y-%m-%dT%H-%M-%S')}-{session_id}.jsonl"


class CodexFormat(ThreadFormat):
    __doc__ = __doc__
    harness = "codex"

    # ── locate ──────────────────────────────────────────────────────────────

    def locate(self, store: StoreRef) -> str:
        wanted = store.session_id or _pointer_text(store.pointer)
        if wanted:
            hits = list((store.home / "sessions").glob(f"*/*/*/rollout-*-{wanted}.jsonl")) \
                + list((store.home / "archived_sessions").glob(f"rollout-*-{wanted}.jsonl"))
            if not hits:
                raise InterchangeError("source_empty", f"codex thread {wanted} not found under {store.home}")
            return str(hits[0])
        found = self.newest((store.home / "sessions").glob("*/*/*/rollout-*.jsonl"))
        if found is None:
            raise InterchangeError("source_empty", f"no codex rollout under {store.home}")
        return str(found)

    # ── read ────────────────────────────────────────────────────────────────

    def read(self, ref: str) -> Thread:
        path = Path(ref)
        records, total, digest = self.read_jsonl(path)
        meta: Dict[str, Optional[str]] = {"session_id": None, "cwd": None, "started_at": None, "cli_version": None, "model": None}
        events: List[Event] = []
        ui_messages: List[Event] = []
        compactions = 0
        for index, value in records:
            if not isinstance(value, dict):
                continue
            rtype = string(value.get("type")) or "?"
            payload = value.get("payload") if isinstance(value.get("payload"), dict) else {}
            ts = string(value.get("timestamp"))
            prov = Provenance(index, rtype)
            if rtype == "session_meta":
                meta["session_id"] = meta["session_id"] or string(payload.get("id")) or string(payload.get("session_id"))
                meta["cwd"] = meta["cwd"] or string(payload.get("cwd"))
                meta["started_at"] = meta["started_at"] or string(payload.get("timestamp")) or ts
                meta["cli_version"] = meta["cli_version"] or string(payload.get("cli_version"))
            elif rtype == "response_item":
                events.extend(self._item_events(payload, prov, ts))
            elif rtype == "compacted":
                # The model continues from the replacement history: so does the thread.
                replacement = payload.get("replacement_history")
                compactions += 1
                if isinstance(replacement, list):
                    events = [e for e in events if e.kind not in (MESSAGE, TOOL_CALL, TOOL_RESULT, THINKING)]
                    for j, item in enumerate(replacement):
                        if isinstance(item, dict):
                            events.extend(self._item_events(item, Provenance(index, "compacted", j), ts))
                elif string(payload.get("message")):
                    events = [e for e in events if e.kind not in (MESSAGE, TOOL_CALL, TOOL_RESULT, THINKING)]
                    events.append(Event(MESSAGE, prov, role=USER, text=payload["message"], timestamp=ts, reason="summary"))
                events.append(Event(CONTEXT, prov, role=SYSTEM, timestamp=ts, reason="compaction"))
            elif rtype == "event_msg":
                etype = string(payload.get("type")) or "?"
                if etype == "user_message" and string(payload.get("message")):
                    ui_messages.append(Event(MESSAGE, prov, role=USER, text=payload["message"], timestamp=ts))
                elif etype == "agent_message" and string(payload.get("message")):
                    ui_messages.append(Event(MESSAGE, prov, role=ASSISTANT, text=payload["message"], timestamp=ts))
                elif etype == "task_started":
                    meta["model"] = meta["model"] or string(payload.get("model"))
                events.append(Event(OPAQUE, prov, timestamp=ts, reason=f"event_{etype}"))
            elif rtype == "turn_context":
                meta["model"] = meta["model"] or string(payload.get("model"))
                events.append(Event(CONTEXT, prov, role=SYSTEM, timestamp=ts, reason="turn_context"))
            else:
                events.append(Event(OPAQUE, prov, timestamp=ts, reason=f"record_{rtype}"))
        if not meta["session_id"]:
            raise InterchangeError("source_unreadable", f"{path.name} has no session_meta")
        if not any(e.is_turn for e in events) and ui_messages:
            # A rollout with UI mirrors but no model-facing items: the mirrors are the thread.
            events.extend(ui_messages)
            events.sort(key=lambda e: e.provenance.record)
        thread = Thread(
            harness=self.harness, source=str(path), session_id=meta["session_id"], cwd=meta["cwd"],
            started_at=meta["started_at"], cli_version=meta["cli_version"], model=meta["model"],
            events=events, records=total, sha256=digest,
        )
        thread.dropped = count_drops(events)
        if compactions:
            thread.dropped["compaction:windows"] = compactions
        if total > len(records):
            thread.dropped["opaque:unparseable_lines"] = total - len(records)
        return thread

    @staticmethod
    def _item_events(payload: Dict[str, Any], prov: Provenance, ts: Optional[str]) -> List[Event]:
        itype = string(payload.get("type")) or "?"
        if itype == "message":
            role = string(payload.get("role")) or "?"
            if role in ("developer", "system"):
                return [Event(CONTEXT, prov, role=SYSTEM, timestamp=ts, reason="system_message")]
            if role not in (USER, ASSISTANT):
                return [Event(OPAQUE, prov, timestamp=ts, reason=f"message_role_{role}")]
            content = payload.get("content")
            if not isinstance(content, list):
                return [Event(OPAQUE, prov, role=role, timestamp=ts, reason="unsupported_message_content")]
            out: List[Event] = []
            for i, block in enumerate(content):
                p = Provenance(prov.record, prov.record_type, i if prov.block is None else prov.block)
                if not isinstance(block, dict):
                    out.append(Event(OPAQUE, p, role=role, timestamp=ts, reason="block_not_object"))
                    continue
                btype = string(block.get("type")) or "?"
                if btype in ("input_text", "output_text", "text"):
                    text = string(block.get("text"))
                    if not text:
                        continue
                    if role == USER and _INJECTED.match(text):
                        out.append(Event(CONTEXT, p, role=USER, timestamp=ts, reason="injected"))
                    else:
                        out.append(Event(MESSAGE, p, role=role, text=text, timestamp=ts))
                elif btype in ("input_image", "image"):
                    out.append(Event(CONTEXT, p, role=role, timestamp=ts, reason="image"))
                else:
                    out.append(Event(OPAQUE, p, role=role, timestamp=ts, reason=f"block_{btype}"))
            return out
        if itype in ("function_call", "custom_tool_call"):
            raw = payload.get("arguments", payload.get("input"))
            tool_input: Any = raw
            if isinstance(raw, str):
                try:
                    tool_input = json.loads(raw)
                except ValueError:
                    tool_input = raw
            return [Event(TOOL_CALL, prov, role=ASSISTANT, timestamp=ts, tool_name=string(payload.get("name")),
                          tool_call_id=string(payload.get("call_id")) or string(payload.get("id")), tool_input=tool_input)]
        if itype in ("function_call_output", "custom_tool_call_output"):
            return [Event(TOOL_RESULT, prov, timestamp=ts, tool_call_id=string(payload.get("call_id")),
                          text=text_of(payload.get("output")))]
        if itype == "reasoning":
            return [Event(THINKING, prov, role=ASSISTANT, timestamp=ts)]
        return [Event(OPAQUE, prov, timestamp=ts, reason=f"item_{itype}")]

    # ── write ───────────────────────────────────────────────────────────────

    def write(self, thread: Thread, store: StoreRef, identity: TargetIdentity) -> Written:
        session_id = self.new_session_id()
        started = _valid_ts(thread.started_at) or self.now()
        path = store.home / rollout_relative_path(session_id, started)
        records: List[Dict[str, Any]] = [{
            "timestamp": started, "type": "session_meta",
            "payload": {
                "session_id": session_id, "id": session_id, "timestamp": started, "cwd": str(store.cwd),
                "originator": "noclick", "cli_version": identity.cli_version or thread.cli_version or "",
                "source": "cli", "model_provider": identity.model_provider or "openai", "history_mode": "legacy",
            },
        }]
        dropped: Counter = Counter()
        seen_calls: set = set()
        counter = 0

        def line(rtype: str, payload: Dict[str, Any], ts: Optional[str]) -> None:
            records.append({"timestamp": _valid_ts(ts) or started, "type": rtype, "payload": payload})

        for event in thread.events:
            if event.is_turn:
                if event.role == USER:
                    line("event_msg", {"type": "user_message", "message": event.text}, event.timestamp)
                    line("response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": event.text}]}, event.timestamp)
                else:
                    line("event_msg", {"type": "agent_message", "message": event.text}, event.timestamp)
                    line("response_item", {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": event.text}]}, event.timestamp)
            elif event.kind == TOOL_CALL:
                call_id = event.tool_call_id
                if not call_id:
                    counter += 1
                    call_id = f"call_nc_{counter:04d}"
                    dropped["tool_call:missing_id"] += 1
                tool_input = event.tool_input
                if not isinstance(tool_input, dict):
                    tool_input = {"input": tool_input if tool_input is not None else ""}
                    dropped["tool_call:non_object_input"] += 1
                seen_calls.add(call_id)
                if not event.tool_name:
                    dropped["tool_call:missing_name"] += 1
                line("response_item", {"type": "function_call", "name": event.tool_name or "unknown_tool",
                                       "arguments": json.dumps(tool_input, ensure_ascii=False), "call_id": call_id}, event.timestamp)
            elif event.kind == TOOL_RESULT:
                call_id = event.tool_call_id
                if not call_id or call_id not in seen_calls:
                    dropped["tool_result:orphan_id"] += 1
                    continue
                line("response_item", {"type": "function_call_output", "call_id": call_id, "output": event.text or ""}, event.timestamp)
            else:
                dropped[event.drop_key] += 1
        return Written(session_id=session_id, native_path=path, records=records, dropped=dropped)


def _pointer_text(pointer: Optional[Path]) -> Optional[str]:
    try:
        return pointer.read_text().strip() or None if pointer else None
    except OSError:
        return None


def _parse_ts(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _valid_ts(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    except ValueError:
        return None
