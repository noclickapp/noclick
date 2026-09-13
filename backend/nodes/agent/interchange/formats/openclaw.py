"""OpenClaw: transcripts in the per-agent SQLite database
``<home>/agents/main/agent/openclaw-agent.sqlite`` (``home`` is the state
dir, ``OPENCLAW_STATE_DIR``).

The Gateway keys a conversation by SESSION KEY — NoClick's runners use
``agent:main:noclick`` in both editions — and ``session_nodes`` maps the key
to the current session id, whose events live in ``transcript_events`` as
the pi-agent JSONL entries (a ``session`` header, then ``message`` entries
chained by ``parentId``: user text, assistant content blocks — ``text``,
``thinking``, ``toolCall`` — and ``toolResult`` messages; ``model_change``,
``thinking_level_change`` and ``custom`` entries are the Gateway's own).
Beside the events the Gateway keeps a projection it refuses to start
without: ``transcript_event_identities``, ``session_transcript_active_events``
(the active branch, with message positions), ``session_transcript_index_state``,
the search FTS and a rewrite watermark — so a writer must produce all of
them, exactly as the Gateway's own writer leaves them. Session ids are
canonicalised to lowercase.

The database has ~100 STRICT tables and only the Gateway can create it: a
target store that does not exist yet is primed with a keyless
``openclaw agent`` run, which creates the schema and fails at model
resolution before reaching any provider. A legacy ``sessions.json`` +
``.jsonl`` layout is not adopted by this version. Validated against
OpenClaw 2026.9.1 (write and resume) — see
``tests/test_session_interchange_drift.py``.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..ir import (
    ASSISTANT, CONTEXT, MESSAGE, OPAQUE, SYSTEM, THINKING, TOOL_CALL, TOOL_RESULT, USER,
    Event, Provenance, StoreRef, TargetIdentity, Thread, count_drops, string, text_of,
)
from .base import InterchangeError, ThreadFormat, Written, db_ref, split_db_ref

SESSION_KEY = "agent:main:noclick"
PRIME_SESSION = "nc-prime"


class OpenClawFormat(ThreadFormat):
    __doc__ = __doc__
    harness = "openclaw"

    @staticmethod
    def db_path(store: StoreRef) -> Path:
        return store.home / "agents" / "main" / "agent" / "openclaw-agent.sqlite"

    # ── locate ──────────────────────────────────────────────────────────────

    def locate(self, store: StoreRef) -> str:
        db = self.db_path(store)
        if not db.is_file():
            raise InterchangeError("source_empty", f"no openclaw agent database at {db}")
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            wanted = (store.session_id or "").lower()
            if wanted and conn.execute("SELECT 1 FROM session_windows WHERE session_id = ?", (wanted,)).fetchone():
                return db_ref(db, wanted)
            row = conn.execute("SELECT current_session_id FROM session_nodes WHERE session_key = ?", (SESSION_KEY,)).fetchone()
            if row is None:
                row = conn.execute("SELECT session_id FROM session_windows WHERE session_id != ? ORDER BY updated_at DESC LIMIT 1", (PRIME_SESSION,)).fetchone()
            if row is None:
                raise InterchangeError("source_empty", f"no openclaw session in {db}")
            return db_ref(db, row[0])

    # ── read ────────────────────────────────────────────────────────────────

    def read(self, ref: str) -> Thread:
        db, sid = split_db_ref(ref)
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            window = conn.execute("SELECT model_provider, model, created_at FROM session_windows WHERE session_id = ?", (sid,)).fetchone()
            if window is None:
                raise InterchangeError("source_unreadable", f"openclaw session {sid} vanished from {db}")
            active = [r[0] for r in conn.execute(
                "SELECT event_seq FROM session_transcript_active_events WHERE session_id = ? ORDER BY active_position", (sid,))]
            rows = conn.execute("SELECT seq, event_json FROM transcript_events WHERE session_id = ? ORDER BY seq", (sid,)).fetchall()
        # The active projection is the branch the Gateway continues; without
        # one (never indexed) every event counts.
        chosen = set(active) if active else None
        events: List[Event] = []
        cwd: Optional[str] = None
        started: Optional[str] = None
        for seq, raw in rows:
            try:
                entry = json.loads(raw)
            except ValueError:
                events.append(Event(OPAQUE, Provenance(seq, "?"), reason="unparseable_event"))
                continue
            etype = string(entry.get("type")) or "?"
            prov = Provenance(seq, etype)
            ts = string(entry.get("timestamp"))
            if etype == "session":
                cwd = cwd or string(entry.get("cwd"))
                started = started or ts
                continue
            if chosen is not None and seq not in chosen:
                events.append(Event(OPAQUE, prov, timestamp=ts, reason="inactive_branch"))
                continue
            if etype != "message":
                reason = "compaction" if etype in ("compaction", "branch_summary") else f"entry_{etype}"
                kind = CONTEXT if etype in ("compaction", "branch_summary") else OPAQUE
                if etype == "compaction" and string(entry.get("summary")):
                    events.append(Event(MESSAGE, prov, role=USER, text=entry["summary"], timestamp=ts, reason="summary"))
                events.append(Event(kind, prov, role=SYSTEM if kind == CONTEXT else None, timestamp=ts, reason=reason))
                continue
            message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
            events.extend(self._message_events(prov, message, ts))
        thread = Thread(
            harness=self.harness, source=ref, session_id=sid, cwd=cwd, started_at=started, cli_version=None,
            model=f"{window[0]}/{window[1]}" if window[0] and window[1] else window[1],
            events=events, records=len(rows), sha256=None,
        )
        thread.dropped = count_drops(events)
        return thread

    @staticmethod
    def _message_events(prov: Provenance, message: Dict[str, Any], ts: Optional[str]) -> List[Event]:
        role = string(message.get("role")) or "?"
        content = message.get("content")
        if role == "toolResult":
            return [Event(TOOL_RESULT, prov, timestamp=ts, tool_call_id=string(message.get("toolCallId")),
                          tool_name=string(message.get("toolName")), text=text_of(content), is_error=message.get("isError") is True)]
        if role not in (USER, ASSISTANT):
            return [Event(CONTEXT, prov, role=SYSTEM, timestamp=ts, reason="system_message")]
        if isinstance(content, str):
            return [Event(MESSAGE, prov, role=role, text=content, timestamp=ts)] if content else []
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
                    out.append(Event(MESSAGE, p, role=role, text=block["text"], timestamp=ts))
            elif btype == "toolCall":
                out.append(Event(TOOL_CALL, p, role=ASSISTANT, timestamp=ts, tool_name=string(block.get("name")),
                                 tool_call_id=string(block.get("id")), tool_input=block.get("arguments", {})))
            elif btype in ("thinking", "redacted_thinking"):
                out.append(Event(THINKING, p, role=ASSISTANT, timestamp=ts))
            elif btype in ("image", "file", "document"):
                out.append(Event(CONTEXT, p, role=role, timestamp=ts, reason=btype))
            else:
                # An assistant block this reader does not know is a drift signal, not bookkeeping.
                out.append(Event(OPAQUE, p, role=role, timestamp=ts, reason=f"block_{btype}") if role == USER
                           else Event(MESSAGE, p, role=None, timestamp=ts, reason=f"unknown_block_{btype}"))
        return out

    # ── write ───────────────────────────────────────────────────────────────

    def write(self, thread: Thread, store: StoreRef, identity: TargetIdentity) -> Written:
        session_id = (store.session_id or f"noclick-{secrets.token_hex(12)}").lower()
        provider, model = _split_model(identity.model or thread.model or "")
        api = "anthropic-messages" if provider == "anthropic" else "openai-completions"
        started = thread.started_at or self.now()
        entries: List[Dict[str, Any]] = [{"type": "session", "version": 3, "id": session_id, "timestamp": started, "cwd": str(store.cwd)}]
        dropped: Counter = Counter()
        parent: Optional[str] = None
        seen_calls: Dict[str, str] = {}  # call id → tool name
        pending_blocks: List[Dict[str, Any]] = []
        pending_ts: Optional[str] = None

        def entry(message: Dict[str, Any], ts: Optional[str]) -> None:
            nonlocal parent
            eid = str(uuid.uuid4())
            entries.append({"type": "message", "id": eid, "parentId": parent, "timestamp": ts or started, "message": message})
            parent = eid

        def flush_assistant() -> None:
            nonlocal pending_blocks, pending_ts
            if pending_blocks:
                entry({"role": "assistant", "content": pending_blocks, "api": api, "provider": provider, "model": model,
                       "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0,
                                 "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}},
                       "stopReason": "toolUse" if any(b["type"] == "toolCall" for b in pending_blocks) else "stop",
                       "timestamp": _ms(pending_ts) or _ms(started) or int(time.time() * 1000)}, pending_ts)
            pending_blocks, pending_ts = [], None

        for event in thread.events:
            if event.is_turn and event.role == USER:
                flush_assistant()
                entry({"role": "user", "content": event.text, "timestamp": _ms(event.timestamp) or int(time.time() * 1000)}, event.timestamp)
            elif event.is_turn:
                pending_ts = pending_ts or event.timestamp
                pending_blocks.append({"type": "text", "text": event.text})
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
                seen_calls[call_id] = event.tool_name or "unknown_tool"
                pending_ts = pending_ts or event.timestamp
                pending_blocks.append({"type": "toolCall", "id": call_id, "name": seen_calls[call_id], "arguments": tool_input})
            elif event.kind == TOOL_RESULT:
                if not event.tool_call_id or event.tool_call_id not in seen_calls:
                    dropped["tool_result:orphan_id"] += 1
                    continue
                flush_assistant()
                entry({"role": "toolResult", "toolCallId": event.tool_call_id, "toolName": event.tool_name or seen_calls[event.tool_call_id],
                       "content": [{"type": "text", "text": event.text or ""}], "isError": bool(event.is_error),
                       "timestamp": _ms(event.timestamp) or int(time.time() * 1000)}, event.timestamp)
            else:
                dropped[event.drop_key] += 1
        flush_assistant()
        return Written(session_id=session_id, native_path=self.db_path(store), records=entries, dropped=dropped)

    def ref_for(self, written: Written, store: StoreRef) -> str:
        return db_ref(self.db_path(store), written.session_id)

    def unwrite(self, written: Written, store: StoreRef) -> None:
        sid = written.session_id
        undo = written.undo
        try:
            with sqlite3.connect(self.db_path(store), timeout=30) as conn:
                for table in ("session_transcript_active_events", "session_transcript_index_state", "transcript_rewrite_watermarks",
                              "transcript_event_identities", "transcript_events", "session_windows"):
                    conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (sid,))
                conn.execute("DELETE FROM session_transcript_fts WHERE session_id = ?", (sid,))
                previous = undo.get("previous_node")
                if previous is None:
                    conn.execute("DELETE FROM session_nodes WHERE session_key = ?", (SESSION_KEY,))
                else:
                    conn.execute("UPDATE session_nodes SET current_session_id = ?, entry_json = ?, updated_at = ? WHERE session_key = ?",
                                 (previous[0], previous[1], previous[2], SESSION_KEY))
        except sqlite3.Error:
            pass

    def install(self, written: Written, store: Optional[StoreRef] = None) -> Path:
        assert store is not None
        db = self.db_path(store)
        if not db.is_file():
            self._prime(store)
        now = int(time.time() * 1000)
        sid = written.session_id
        entries = written.records
        provider, model = _split_model(_provider_model(entries))
        try:
            with sqlite3.connect(db, timeout=30) as conn:
                if conn.execute("SELECT 1 FROM session_windows WHERE session_id = ?", (sid,)).fetchone():
                    raise InterchangeError("install_failed", f"openclaw session {sid} already exists")
                written.undo = {"previous_node": conn.execute(
                    "SELECT current_session_id, entry_json, updated_at FROM session_nodes WHERE session_key = ?", (SESSION_KEY,)).fetchone()}
                conn.execute(
                    "INSERT INTO session_nodes (session_key, current_session_id, entry_json, entry_valid, updated_at, last_interaction_at, last_activity_at) "
                    "VALUES (?,?,?,?,?,?,?) ON CONFLICT(session_key) DO UPDATE SET current_session_id = excluded.current_session_id, "
                    "entry_json = excluded.entry_json, entry_valid = 1, updated_at = excluded.updated_at, last_activity_at = excluded.last_activity_at",
                    (SESSION_KEY, sid, json.dumps({"sessionId": sid, "updatedAt": now, "sessionStartedAt": now - 1, "delivery": {"kind": "none"}}), 1, now, now, now),
                )
                conn.execute(
                    "INSERT INTO session_windows (session_id, session_key, session_scope, created_at, updated_at, transcript_updated_at, "
                    "transcript_observed_at, session_entry_provenance, acp_owned, model_provider, model, agent_harness_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, SESSION_KEY, "conversation", now - 1, now, now, now, 1, 0, provider or None, model or None, "openclaw"),
                )
                active = message_pos = 0
                leaf: Optional[str] = None
                for seq, e in enumerate(entries):
                    conn.execute("INSERT INTO transcript_events (session_id, seq, event_json, created_at) VALUES (?,?,?,?)", (sid, seq, json.dumps(e, ensure_ascii=False), now))
                    conn.execute("INSERT INTO transcript_event_identities (session_id, event_id, seq, event_type, parent_id, created_at) VALUES (?,?,?,?,?,?)",
                                 (sid, e.get("id") or sid, seq, e["type"], e.get("parentId"), now))
                    if e["type"] == "session":
                        continue
                    leaf = e.get("id") or leaf
                    mp = None
                    if e["type"] == "message":
                        mp = message_pos
                        message_pos += 1
                        m = e["message"]
                        if m.get("role") in (USER, ASSISTANT):
                            conn.execute("INSERT INTO session_transcript_fts (text, session_id, message_id, role, timestamp) VALUES (?,?,?,?,?)",
                                         (text_of(m.get("content")), sid, e["id"], m["role"], float(m.get("timestamp") or now)))
                    conn.execute("INSERT INTO session_transcript_active_events (session_id, active_position, event_seq, message_position, context_eligible) VALUES (?,?,?,?,?)",
                                 (sid, active, seq, mp, 1))
                    active += 1
                conn.execute("INSERT INTO session_transcript_index_state (session_id, indexed_seq, leaf_event_id, needs_rebuild, active_event_count, active_message_count, updated_at) VALUES (?,?,?,?,?,?,?)",
                             (sid, len(entries) - 1, leaf, 0, active, message_pos, now))
                conn.execute("INSERT INTO transcript_rewrite_watermarks (session_id, generation, updated_at) VALUES (?,?,?)", (sid, secrets.token_hex(16), now))
        except sqlite3.Error as e:
            raise InterchangeError("install_failed", f"openclaw store {db}: {e}") from e
        return db

    def _prime(self, store: StoreRef) -> None:
        """Create the agent database the only way there is: an agent run that
        builds the schema and then fails at model resolution. It runs under
        its own config with no provider and no key, so whatever the store's
        real config names, nothing can be reached (a real provider would
        have been sent the word "prime")."""
        cli = shutil.which("openclaw", path=(store.environ or os.environ).get("PATH"))
        if not cli:
            raise InterchangeError("install_failed", "openclaw is not on PATH and its store does not exist yet")
        cwd = store.cwd if store.cwd.is_dir() else store.home
        config = store.home / ".nc_interchange" / "prime-config.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"agents": {"defaults": {"workspace": str(cwd), "sandbox": {"mode": "off"}}}, "tools": {"exec": {"ask": "off"}}}))
        env = {k: v for k, v in (store.environ or os.environ).items() if not k.endswith("_API_KEY") and not k.endswith("_BASE_URL")}
        env.update({"OPENCLAW_STATE_DIR": str(store.home), "OPENCLAW_HOME": str(store.home), "OPENCLAW_CONFIG_PATH": str(config),
                    "OPENCLAW_DISABLE_BONJOUR": "1", "OPENCLAW_NO_RESPAWN": "1", "OPENCLAW_SKIP_CHANNELS": "1",
                    "OPENCLAW_EXEC_SHELL_SNAPSHOT": "0", "NO_COLOR": "1"})
        try:
            subprocess.run([cli, "agent", "--local", "--json", "--message", "prime", "--session-id", PRIME_SESSION, "--model", "nc-prime/nc-prime"],
                           cwd=cwd, env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as e:
            raise InterchangeError("install_failed", f"openclaw prime run: {e}") from e
        if not self.db_path(store).is_file():
            raise InterchangeError("install_failed", "openclaw prime run did not create the agent database")


# ── helpers ──────────────────────────────────────────────────────────────────


def _split_model(model: str) -> Tuple[str, str]:
    provider, _, name = model.partition("/")
    return (provider, name) if name else ("", model)


def _provider_model(entries: List[Dict[str, Any]]) -> str:
    for e in entries:
        m = e.get("message") or {}
        if e.get("type") == "message" and m.get("role") == "assistant" and m.get("provider"):
            return f"{m['provider']}/{m.get('model') or ''}"
    return ""


def _ms(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    from datetime import datetime, timezone

    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)
    except ValueError:
        return None
