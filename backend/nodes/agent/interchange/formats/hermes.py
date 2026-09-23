"""Hermes: sessions in ``<home>/state.db`` (``home`` is ``HERMES_HOME``).

A ``sessions`` row per conversation and ``messages`` rows in insertion
order: ``user``/``assistant`` text, assistant rows carrying OpenAI-style
``tool_calls`` JSON, and ``tool`` rows keyed by ``tool_call_id`` with the
tool's name and output. ``active = 1`` rows are the live thread (rewinds
soft-delete with ``active = 0``, in-place compaction keeps
``compacted = 1`` rows for display); structured content is stored with a
``\\x00json:`` prefix. NoClick drives the Runs API with a FIXED session id,
``noclick``, in both editions, so that id is the thread.

The Gateway creates the database at boot, which is after a move runs; a
missing store is created here with the pinned schema's four core tables
(``schema_version``, ``system_prompts``, ``sessions``, ``messages`` —
verbatim from the pinned source) and the pinned schema version, and the
Gateway adds every other table it wants at its own boot (``CREATE TABLE IF
NOT EXISTS``). Validated against Hermes v2026.9.21 / schema 26 (boot on a
store built here, and replay) — see ``tests/test_session_interchange_drift.py``.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..ir import (
    ASSISTANT, CONTEXT, MESSAGE, OPAQUE, SYSTEM, THINKING, TOOL_CALL, TOOL_RESULT, USER,
    Event, Provenance, StoreRef, TargetIdentity, Thread, count_drops, string, text_of,
)
from . import sqlite_compat as sqlite
from .base import InterchangeError, ThreadFormat, Written, db_ref, split_db_ref

SESSION_ID = "noclick"
SCHEMA_VERSION = 26
CONTENT_JSON_PREFIX = "\x00json:"

#: The pinned schema's core tables, verbatim.
SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS system_prompts (
    hash TEXT PRIMARY KEY,
    prompt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    user_id TEXT,
    session_key TEXT,
    chat_id TEXT,
    chat_type TEXT,
    thread_id TEXT,
    display_name TEXT,
    origin_json TEXT,
    expiry_finalized INTEGER DEFAULT 0,
    model TEXT,
    model_config TEXT,
    system_prompt TEXT,
    system_prompt_hash TEXT,
    parent_session_id TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    cwd TEXT,
    git_branch TEXT,
    git_repo_root TEXT,
    git_metadata_generation INTEGER NOT NULL DEFAULT 0,
    billing_provider TEXT,
    billing_base_url TEXT,
    billing_mode TEXT,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    cost_status TEXT,
    cost_source TEXT,
    pricing_version TEXT,
    title TEXT,
    title_source TEXT,
    last_activity_at REAL,
    last_activity_description TEXT,
    last_activity_provenance TEXT,
    api_call_count INTEGER DEFAULT 0,
    handoff_state TEXT,
    handoff_platform TEXT,
    handoff_error TEXT,
    compression_failure_cooldown_until REAL,
    compression_failure_error TEXT,
    compression_fallback_streak INTEGER NOT NULL DEFAULT 0,
    compression_ineffective_count INTEGER NOT NULL DEFAULT 0,
    profile_name TEXT,
    rewind_count INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    last_read_at REAL,
    FOREIGN KEY (parent_session_id) REFERENCES sessions(id),
    FOREIGN KEY (system_prompt_hash) REFERENCES system_prompts(hash)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    effect_disposition TEXT,
    timestamp REAL NOT NULL,
    token_count INTEGER,
    finish_reason TEXT,
    reasoning TEXT,
    reasoning_content TEXT,
    reasoning_details TEXT,
    codex_reasoning_items TEXT,
    codex_message_items TEXT,
    platform_message_id TEXT,
    observed INTEGER DEFAULT 0,
    _compressed_summary INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    compacted INTEGER NOT NULL DEFAULT 0,
    api_content TEXT,
    display_kind TEXT,
    display_metadata TEXT
);
"""


class HermesFormat(ThreadFormat):
    __doc__ = __doc__
    harness = "hermes_agent"

    @staticmethod
    def db_path(store: StoreRef) -> Path:
        return store.home / "state.db"

    # ── locate ──────────────────────────────────────────────────────────────

    def locate(self, store: StoreRef) -> str:
        db = self.db_path(store)
        if not db.is_file():
            raise InterchangeError("source_empty", f"no hermes state database at {db}")
        sid = store.session_id or SESSION_ID
        with sqlite.connect(db, readonly=True) as conn:
            if conn.execute("SELECT 1 FROM sessions WHERE id = ?", (sid,)).fetchone() is None:
                raise InterchangeError("source_empty", f"hermes session {sid} not in {db}")
            if conn.execute("SELECT 1 FROM messages WHERE session_id = ? AND active = 1 AND role IN ('user','assistant') LIMIT 1", (sid,)).fetchone() is None:
                raise InterchangeError("source_empty", f"hermes session {sid} holds no active messages")
        return db_ref(db, sid)

    # ── read ────────────────────────────────────────────────────────────────

    def read(self, ref: str) -> Thread:
        db, sid = split_db_ref(ref)
        with sqlite.connect(db, readonly=True) as conn:
            session = conn.execute("SELECT model, started_at, cwd FROM sessions WHERE id = ?", (sid,)).fetchone()
            if session is None:
                raise InterchangeError("source_unreadable", f"hermes session {sid} vanished from {db}")
            rows = conn.execute(
                "SELECT id, role, content, tool_call_id, tool_calls, tool_name, timestamp, reasoning, reasoning_content, _compressed_summary "
                "FROM messages WHERE session_id = ? AND active = 1 ORDER BY id", (sid,)).fetchall()
        events: List[Event] = []
        for index, (rid, role, content, tool_call_id, tool_calls, tool_name, ts_f, reasoning, reasoning_content, summary) in enumerate(rows):
            prov = Provenance(index, f"message:{role}")
            ts = _iso(ts_f)
            text = _decode(content)
            if role == "tool":
                events.append(Event(TOOL_RESULT, prov, timestamp=ts, tool_call_id=string(tool_call_id), tool_name=string(tool_name), text=text))
                continue
            if role not in (USER, ASSISTANT):
                events.append(Event(CONTEXT, prov, role=SYSTEM, timestamp=ts, reason="system_message"))
                continue
            if role == ASSISTANT and (reasoning or reasoning_content):
                events.append(Event(THINKING, prov, role=ASSISTANT, timestamp=ts))
            if text:
                events.append(Event(MESSAGE, prov, role=role, text=text, timestamp=ts, reason="summary" if summary else ""))
            if role == ASSISTANT and tool_calls:
                try:
                    calls = json.loads(tool_calls) if isinstance(tool_calls, str) else tool_calls
                except ValueError:
                    calls = None
                if not isinstance(calls, list):
                    events.append(Event(OPAQUE, prov, role=ASSISTANT, timestamp=ts, reason="unparseable_tool_calls"))
                    continue
                for i, call in enumerate(calls):
                    fn = call.get("function") if isinstance(call, dict) and isinstance(call.get("function"), dict) else {}
                    args: Any = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except ValueError:
                            pass
                    events.append(Event(TOOL_CALL, Provenance(index, "message:assistant", i), role=ASSISTANT, timestamp=ts,
                                        tool_name=string(fn.get("name")), tool_call_id=string(call.get("id")) if isinstance(call, dict) else None,
                                        tool_input=args if args is not None else {}))
        thread = Thread(harness=self.harness, source=ref, session_id=sid, cwd=session[2], started_at=_iso(session[1]),
                        cli_version=None, model=session[0], events=events, records=len(rows), sha256=None)
        thread.dropped = count_drops(events)
        return thread

    # ── write ───────────────────────────────────────────────────────────────

    def write(self, thread: Thread, store: StoreRef, identity: TargetIdentity) -> Written:
        sid = store.session_id or SESSION_ID
        base = _epoch(thread.started_at) or time.time()
        rows: List[Dict[str, Any]] = []
        dropped: Counter = Counter()
        seen_calls: set = set()
        clock = base

        def at(ts: Optional[str]) -> float:
            nonlocal clock
            clock = max(clock + 0.001, _epoch(ts) or 0.0)
            return clock

        for event in thread.events:
            if event.is_turn:
                rows.append({"role": event.role, "content": event.text, "timestamp": at(event.timestamp),
                             "finish_reason": "stop" if event.role == ASSISTANT else None})
            elif event.kind == TOOL_CALL:
                call_id = event.tool_call_id
                if not call_id:
                    call_id = f"call_nc_{len(seen_calls) + 1:04d}"
                    dropped["tool_call:missing_id"] += 1
                tool_input = event.tool_input
                if not isinstance(tool_input, dict):
                    tool_input = {"input": tool_input if tool_input is not None else ""}
                    dropped["tool_call:non_object_input"] += 1
                if not event.tool_name:
                    dropped["tool_call:missing_name"] += 1
                seen_calls.add(call_id)
                call = {"id": call_id, "type": "function", "function": {"name": event.tool_name or "unknown_tool", "arguments": json.dumps(tool_input, ensure_ascii=False)}}
                # OpenAI shape: the call rides the assistant turn that made it.
                if rows and rows[-1]["role"] == ASSISTANT and rows[-1].get("tool_calls") is not None:
                    rows[-1]["tool_calls"].append(call)
                elif rows and rows[-1]["role"] == ASSISTANT and not rows[-1].get("tool_calls") and rows[-1].get("finish_reason") == "stop" and event.timestamp == rows[-1].get("_ts"):
                    rows[-1].update({"tool_calls": [call], "finish_reason": "tool_calls"})
                else:
                    rows.append({"role": ASSISTANT, "content": None, "timestamp": at(event.timestamp), "finish_reason": "tool_calls", "tool_calls": [call]})
            elif event.kind == TOOL_RESULT:
                if not event.tool_call_id or event.tool_call_id not in seen_calls:
                    dropped["tool_result:orphan_id"] += 1
                    continue
                rows.append({"role": "tool", "content": event.text or "", "tool_call_id": event.tool_call_id,
                             "tool_name": event.tool_name or _name_of(rows, event.tool_call_id), "timestamp": at(event.timestamp)})
            else:
                dropped[event.drop_key] += 1
        for r in rows:
            r.pop("_ts", None)
        session = {"id": sid, "source": "api", "model": identity.model or thread.model, "started_at": base, "cwd": str(store.cwd),
                   "title": next((r["content"] for r in rows if r["role"] == USER and r.get("content")), "Moved thread")[:80],
                   "message_count": sum(r["role"] in (USER, ASSISTANT) for r in rows), "tool_call_count": len(seen_calls)}
        return Written(session_id=sid, native_path=self.db_path(store), records=[session, *rows], dropped=dropped)

    def ref_for(self, written: Written, store: StoreRef) -> str:
        return db_ref(self.db_path(store), written.session_id)

    def unwrite(self, written: Written, store: StoreRef) -> None:
        undo = written.undo
        if not undo:
            return
        try:
            with sqlite.connect(self.db_path(store)) as conn:
                conn.execute("DELETE FROM messages WHERE session_id = ? AND id > ?", (written.session_id, undo["max_id_before"]))
                for rid in undo["retired_ids"]:
                    conn.execute("UPDATE messages SET active = 1 WHERE id = ?", (rid,))
        except sqlite.Error:
            pass

    def install(self, written: Written, store: Optional[StoreRef] = None) -> Path:
        assert store is not None
        db = self.db_path(store)
        session, rows = written.records[0], written.records[1:]
        try:
            db.parent.mkdir(parents=True, exist_ok=True)
            with sqlite.connect(db) as conn:
                if conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'messages'").fetchone() is None:
                    conn.executescript(SCHEMA_SQL)
                    if conn.execute("SELECT 1 FROM schema_version").fetchone() is None:
                        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
                # An older thread under the same fixed id is history the
                # runner would replay ahead of the moved one: retire it.
                retired = [r[0] for r in conn.execute("SELECT id FROM messages WHERE session_id = ? AND active = 1", (session["id"],))]
                written.undo = {"retired_ids": retired, "max_id_before": (conn.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()[0])}
                conn.execute("UPDATE messages SET active = 0 WHERE session_id = ? AND active = 1", (session["id"],))
                conn.execute(
                    "INSERT INTO sessions (id, source, model, started_at, cwd, title, message_count, tool_call_count) VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET model = COALESCE(excluded.model, sessions.model), title = excluded.title, "
                    "message_count = excluded.message_count, tool_call_count = excluded.tool_call_count, ended_at = NULL, end_reason = NULL, archived = 0",
                    (session["id"], session["source"], session["model"], session["started_at"], session["cwd"], session["title"], session["message_count"], session["tool_call_count"]),
                )
                for r in rows:
                    conn.execute(
                        "INSERT INTO messages (session_id, role, content, tool_call_id, tool_calls, tool_name, timestamp, finish_reason, active) VALUES (?,?,?,?,?,?,?,?,1)",
                        (session["id"], r["role"], r.get("content"), r.get("tool_call_id"),
                         json.dumps(r["tool_calls"], ensure_ascii=False) if r.get("tool_calls") else None,
                         r.get("tool_name"), r["timestamp"], r.get("finish_reason")),
                    )
        except sqlite.Error as e:
            raise InterchangeError("install_failed", f"hermes store {db}: {e}") from e
        return db


# ── helpers ──────────────────────────────────────────────────────────────────


def _decode(content: Any) -> str:
    if isinstance(content, str) and content.startswith(CONTENT_JSON_PREFIX):
        try:
            return text_of(json.loads(content[len(CONTENT_JSON_PREFIX):]))
        except ValueError:
            return content
    return content if isinstance(content, str) else ""


def _name_of(rows: List[Dict[str, Any]], call_id: str) -> str:
    for r in reversed(rows):
        for call in r.get("tool_calls") or []:
            if call.get("id") == call_id:
                return call["function"]["name"]
    return ""


def _iso(epoch: Any) -> Optional[str]:
    if not isinstance(epoch, (int, float)):
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch)) + f".{int((epoch % 1) * 1000):03d}Z"


def _epoch(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    from datetime import datetime, timezone

    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except ValueError:
        return None
