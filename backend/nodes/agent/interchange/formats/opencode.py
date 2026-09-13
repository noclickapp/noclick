"""OpenCode: sessions in one SQLite database, ``<home>/opencode/opencode.db``
(``home`` is the XDG data home the CLI reads, ``~/.local/share``).

A session row holds the id (``ses_…``), directory, title and version; a
``message`` row per turn (``data`` is the public message object: role,
time, model, parentID for assistant replies) and ``part`` rows under it
(``data``: ``text``, ``reasoning``, ``tool`` — one part carries the call
AND its result in ``state`` — ``step-start``/``step-finish``, files,
snapshots). Ids are ``<prefix>_<12 hex><14 alnum>``.

The database is the CLI's; a thread is written through its public importer
(``opencode import <bundle.json>``: ``{info, messages: [{info, parts}]}``,
the same shape ``opencode export`` prints), which owns the schema, so the
binary must be on PATH where a move runs — it is, in the target's sandbox.
Reading is direct, since the source volume is mounted in a sandbox that has
no ``opencode``. NoClick's runner resumes by the id in its pointer file
(``.nc_session`` beside the database hosted, ``.noclick-opencode-session``
in the local workdir). Validated against OpenCode 1.18.29 (import and
resume) — see ``tests/test_session_interchange_drift.py``.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
import string as _string
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..ir import (
    ASSISTANT, CONTEXT, MESSAGE, OPAQUE, THINKING, TOOL_CALL, TOOL_RESULT, USER,
    Event, Provenance, StoreRef, TargetIdentity, Thread, count_drops, string, text_of,
)
from .base import InterchangeError, ThreadFormat, Written, db_ref, pointer_text, split_db_ref, write_new_file

_ALNUM = _string.ascii_letters + _string.digits


def native_id(prefix: str, at_ms: int) -> str:
    """``<prefix>_<12 hex of the millisecond clock><14 random alnum>`` — the
    CLI's own id scheme, so ordering by id agrees with time."""
    return f"{prefix}_{at_ms:012x}{''.join(secrets.choice(_ALNUM) for _ in range(14))}"


class OpenCodeFormat(ThreadFormat):
    __doc__ = __doc__
    harness = "opencode"

    @staticmethod
    def db_path(store: StoreRef) -> Path:
        return store.home / "opencode" / "opencode.db"

    # ── locate ──────────────────────────────────────────────────────────────

    def locate(self, store: StoreRef) -> str:
        db = self.db_path(store)
        if not db.is_file():
            raise InterchangeError("source_empty", f"no opencode database at {db}")
        wanted = store.session_id or pointer_text(store.pointer)
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            if wanted:
                if conn.execute("SELECT 1 FROM session WHERE id = ?", (wanted,)).fetchone() is None:
                    raise InterchangeError("source_empty", f"opencode session {wanted} not in {db}")
                return db_ref(db, wanted)
            row = conn.execute("SELECT id FROM session ORDER BY time_updated DESC LIMIT 1").fetchone()
        if row is None:
            raise InterchangeError("source_empty", f"no opencode session in {db}")
        return db_ref(db, row[0])

    # ── read ────────────────────────────────────────────────────────────────

    def read(self, ref: str) -> Thread:
        db, sid = split_db_ref(ref)
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            session = conn.execute("SELECT directory, version, title, time_created FROM session WHERE id = ?", (sid,)).fetchone()
            if session is None:
                raise InterchangeError("source_unreadable", f"opencode session {sid} vanished from {db}")
            messages = conn.execute("SELECT id, data FROM message WHERE session_id = ? ORDER BY time_created, id", (sid,)).fetchall()
            parts = conn.execute("SELECT message_id, data FROM part WHERE session_id = ? ORDER BY time_created, id", (sid,)).fetchall()
        by_message: Dict[str, List[Any]] = {}
        for message_id, data in parts:
            by_message.setdefault(message_id, []).append(_json(data))
        events: List[Event] = []
        model: Optional[str] = None
        for index, (message_id, data) in enumerate(messages):
            info = _json(data) or {}
            role = string(info.get("role")) or "?"
            ts = _iso(((info.get("time") or {}).get("created")))
            if role == ASSISTANT:
                model = model or string(info.get("modelID"))
            for i, part in enumerate(by_message.get(message_id, [])):
                prov = Provenance(index, f"message:{role}", i)
                if not isinstance(part, dict):
                    events.append(Event(OPAQUE, prov, role=role, timestamp=ts, reason="part_not_object"))
                    continue
                ptype = string(part.get("type")) or "?"
                if ptype == "text":
                    if role in (USER, ASSISTANT) and string(part.get("text")):
                        events.append(Event(MESSAGE, prov, role=role, text=part["text"], timestamp=ts))
                    elif string(part.get("text")):
                        events.append(Event(CONTEXT, prov, role=role, timestamp=ts, reason="system_message"))
                elif ptype == "reasoning":
                    events.append(Event(THINKING, prov, role=ASSISTANT, timestamp=ts))
                elif ptype == "tool":
                    state = part.get("state") if isinstance(part.get("state"), dict) else {}
                    status = string(state.get("status")) or "?"
                    if status not in ("completed", "error"):
                        events.append(Event(OPAQUE, prov, role=ASSISTANT, timestamp=ts, reason=f"tool_{status}"))
                        continue
                    call_id = string(part.get("callID")) or string(part.get("id"))
                    events.append(Event(TOOL_CALL, prov, role=ASSISTANT, timestamp=ts, tool_name=string(part.get("tool")),
                                        tool_call_id=call_id, tool_input=state.get("input", {})))
                    output = state.get("output") if status == "completed" else (state.get("error") or state.get("output"))
                    events.append(Event(TOOL_RESULT, prov, timestamp=ts, tool_call_id=call_id, text=text_of(output) if not isinstance(output, str) else output,
                                        is_error=status == "error"))
                elif ptype in ("step-start", "step-finish"):
                    events.append(Event(OPAQUE, prov, role=role, timestamp=ts, reason=f"part_{ptype}"))
                elif ptype in ("file", "snapshot", "patch", "agent", "subtask", "compaction"):
                    events.append(Event(CONTEXT, prov, role=role, timestamp=ts, reason=f"part_{ptype}"))
                else:
                    events.append(Event(OPAQUE, prov, role=role, timestamp=ts, reason=f"part_{ptype}"))
        thread = Thread(
            harness=self.harness, source=ref, session_id=sid, cwd=session[0], started_at=_iso(session[3]),
            cli_version=session[1], model=model, events=events, records=len(messages) + len(parts), sha256=None,
        )
        thread.dropped = count_drops(events)
        return thread

    # ── write ───────────────────────────────────────────────────────────────

    def write(self, thread: Thread, store: StoreRef, identity: TargetIdentity) -> Written:
        now_ms = int(time.time() * 1000)
        started_ms = _ms(thread.started_at) or now_ms
        session_id = native_id("ses", started_ms)
        provider, model = _split_model(identity.model or thread.model or "")
        dropped: Counter = Counter()
        messages: List[Dict[str, Any]] = []
        clock = started_ms
        current: Optional[Dict[str, Any]] = None  # the assistant message being assembled
        last_user_id: Optional[str] = None
        open_calls: Dict[str, Dict[str, Any]] = {}

        def tick() -> int:
            nonlocal clock
            clock += 1
            return clock

        def close_assistant() -> None:
            nonlocal current
            if current is None:
                return
            for call in open_calls.values():  # a call the source never answered
                call["state"]["status"] = "error"
                call["state"]["error"] = "no result recorded"
                dropped["tool_call:unanswered"] += 1
            open_calls.clear()
            finish = "tool-calls" if any(p["type"] == "tool" for p in current["parts"]) else "stop"
            current["info"]["finish"] = finish
            current["info"]["time"]["completed"] = tick()
            current["parts"].append(_part("step-finish", session_id, current["info"]["id"], tick(), reason=finish, cost=0,
                                          tokens={"total": 0, "input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}))
            current = None

        def open_assistant(at: int) -> Dict[str, Any]:
            nonlocal current
            if current is None:
                message_id = native_id("msg", at)
                current = {"info": {
                    "id": message_id, "sessionID": session_id, "role": "assistant", "time": {"created": at},
                    "parentID": last_user_id, "modelID": model, "providerID": provider, "mode": "build", "agent": "build",
                    "path": {"cwd": str(store.cwd), "root": str(store.cwd)}, "cost": 0,
                    "tokens": {"total": 0, "input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}},
                }, "parts": [_part("step-start", session_id, message_id, at)]}
                messages.append(current)
            return current

        for event in thread.events:
            at = _ms(event.timestamp) or tick()
            clock = max(clock, at)
            if event.is_turn and event.role == USER:
                close_assistant()
                last_user_id = native_id("msg", at)
                messages.append({"info": {"id": last_user_id, "sessionID": session_id, "role": "user", "time": {"created": at},
                                          "agent": "build", "model": {"providerID": provider, "modelID": model}},
                                 "parts": [_part("text", session_id, last_user_id, at, text=event.text)]})
            elif event.is_turn:
                message = open_assistant(at)
                message["parts"].append(_part("text", session_id, message["info"]["id"], at, text=event.text, time={"start": at, "end": at}))
            elif event.kind == TOOL_CALL:
                message = open_assistant(at)
                call_id = event.tool_call_id
                if not call_id:
                    call_id = f"call_nc_{len(open_calls) + 1:04d}"
                    dropped["tool_call:missing_id"] += 1
                tool_input = event.tool_input
                if not isinstance(tool_input, dict):
                    tool_input = {"input": tool_input if tool_input is not None else ""}
                    dropped["tool_call:non_object_input"] += 1
                if not event.tool_name:
                    dropped["tool_call:missing_name"] += 1
                part = _part("tool", session_id, message["info"]["id"], at, callID=call_id, tool=event.tool_name or "unknown_tool",
                             state={"status": "completed", "input": tool_input, "output": "", "title": event.tool_name or "", "metadata": {}, "time": {"start": at, "end": at}})
                message["parts"].append(part)
                open_calls[call_id] = part
            elif event.kind == TOOL_RESULT:
                part = open_calls.pop(event.tool_call_id or "", None)
                if part is None:
                    dropped["tool_result:orphan_id"] += 1
                    continue
                part["state"]["output"] = event.text or ""
                part["state"]["time"]["end"] = at
                if event.is_error:
                    part["state"]["status"] = "error"
                    part["state"]["error"] = event.text or "error"
            else:
                dropped[event.drop_key] += 1
        close_assistant()
        first_user = next((e.text for e in thread.events if e.is_turn and e.role == USER), "") or ""
        bundle = {
            "info": {
                "id": session_id, "slug": "moved-thread", "projectID": "global", "directory": str(store.cwd),
                "title": (first_user.strip().splitlines() or ["Moved thread"])[0][:80] or "Moved thread",
                "version": identity.cli_version or thread.cli_version or "", "summary": {"additions": 0, "deletions": 0, "files": 0},
                "cost": 0, "tokens": {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}},
                "time": {"created": started_ms, "updated": clock},
            },
            "messages": messages,
        }
        return Written(session_id=session_id, native_path=self.db_path(store), records=[bundle], dropped=dropped)

    def ref_for(self, written: Written, store: StoreRef) -> str:
        return db_ref(self.db_path(store), written.session_id)

    def unwrite(self, written: Written, store: StoreRef) -> None:
        """The CLI has no delete; a session no pointer names is inert, and
        the bundle it came from goes."""
        bundle = written.undo.get("bundle")
        if bundle:
            Path(bundle).unlink(missing_ok=True)

    def install(self, written: Written, store: Optional[StoreRef] = None) -> Path:
        """Import the bundle through the CLI, which owns the database schema."""
        assert store is not None
        cli = shutil.which("opencode", path=(store.environ or os.environ).get("PATH"))
        if not cli:
            raise InterchangeError("install_failed", "opencode is not on PATH where the move runs")
        bundle_path = store.home / ".nc_interchange" / f"bundle-{written.session_id}.json"
        write_new_file(bundle_path, json.dumps(written.records[0], ensure_ascii=False).encode())
        written.undo["bundle"] = str(bundle_path)
        env = {**(store.environ or os.environ), "XDG_DATA_HOME": str(store.home), "OPENCODE_DISABLE_AUTOUPDATE": "true", "OPENCODE_DISABLE_PRUNE": "true"}
        cwd = store.cwd if store.cwd.is_dir() else store.home
        try:
            proc = subprocess.run([cli, "import", str(bundle_path)], cwd=cwd, env=env, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as e:
            raise InterchangeError("install_failed", f"opencode import: {e}") from e
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0 or f"Imported session: {written.session_id}" not in out:
            raise InterchangeError("install_failed", f"opencode import exit {proc.returncode}: {out[-800:]}")
        return self.db_path(store)


# ── helpers ──────────────────────────────────────────────────────────────────


def _part(ptype: str, session_id: str, message_id: str, at: int, **fields: Any) -> Dict[str, Any]:
    return {"id": native_id("prt", at), "sessionID": session_id, "messageID": message_id, "type": ptype, **fields}


def _split_model(model: str) -> Tuple[str, str]:
    provider, _, name = model.partition("/")
    return (provider, name) if name else ("opencode", model)


def _json(data: Any) -> Any:
    try:
        return json.loads(data) if isinstance(data, (str, bytes)) else data
    except ValueError:
        return None


def _iso(ms: Any) -> Optional[str]:
    if not isinstance(ms, (int, float)):
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms / 1000)) + f".{int(ms % 1000):03d}Z"


def _ms(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    from datetime import datetime, timezone

    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)
    except ValueError:
        return None
