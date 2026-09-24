"""The thread interchange engine (nodes/agent/interchange).

A thread moves as the target harness's own session store, and the verdict
is what the TARGET's reader sees after the write — the same skeleton of
messages and paired tool calls the source held. Fixtures are fictional
threads in the record shapes the pinned harnesses write today (Claude Code
2.1.26x with its bookkeeping records, abandoned branches, subagent
sidechains and compaction; a paginated Codex rollout with ordinals, injected
context, custom tool calls, encrypted reasoning and a compaction window),
so a harness bump that changes those shapes fails here before it fails a
user. The E2E on real binaries is the other half.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from nodes.agent import interchange as ic
from nodes.agent import session_interchange as si
from nodes.agent.interchange import formats
from nodes.agent.interchange.formats import claude_code as claude_fmt
from nodes.agent.interchange.formats import codex as codex_fmt

SESSION = "6f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f"
CWD = "/home/casey/work/acme-api"
PACKAGE = Path(ic.__file__).parent

# The conversation every fixture holds: prompt → assistant text → a tool
# call → its result → the reply. Two harnesses, one skeleton.
EXPECTED_ROLES = ["user", "assistant", "assistant"]


# ── fixtures ────────────────────────────────────────────────────────────────

def _claude_records(cwd: str) -> list:
    ids = [str(uuid.uuid4()) for _ in range(12)]
    ts = "2026-09-12T10:00:{:02d}.000Z"
    base = {"isSidechain": False, "userType": "external", "cwd": cwd, "sessionId": SESSION, "version": "2.1.281",
            "gitBranch": "main", "entrypoint": "cli", "slug": "auth-callback"}
    msg_id = "msg_01"
    return [
        {"type": "mode", "mode": "default", "sessionId": SESSION},
        {"type": "bridge-session", "bridgeSessionId": "b1", "sessionId": SESSION, "lastSequenceNum": 0},
        {"type": "queue-operation", "operation": "enqueue", "timestamp": ts.format(0), "sessionId": SESSION, "content": "Which tests cover the auth callback?"},
        {**base, "parentUuid": None, "type": "user", "uuid": ids[0], "timestamp": ts.format(1), "promptId": str(uuid.uuid4()),
         "turnOrigin": "sdk", "message": {"role": "user", "content": "Which tests cover the auth callback?"}},
        # the CLI's own context injection: never a turn
        {**base, "parentUuid": ids[0], "type": "user", "uuid": ids[1], "timestamp": ts.format(1), "isMeta": True,
         "message": {"role": "user", "content": "# AGENTS.md\nBe terse."}},
        # a hook fired between turns: a system record inside the chain
        {**base, "parentUuid": ids[1], "type": "system", "uuid": ids[2], "timestamp": ts.format(1), "level": "info",
         "content": "SessionStart hook ran", "hookCount": 1, "isMeta": True},
        {**base, "parentUuid": ids[2], "type": "attachment", "uuid": ids[3], "timestamp": ts.format(1),
         "attachment": {"type": "total_tokens_reminder", "text": "<total_tokens>1000 tokens left</total_tokens>"},
         "rendered": "<total_tokens>1000 tokens left</total_tokens>"},
        {**base, "parentUuid": ids[3], "type": "attachment", "uuid": ids[11], "timestamp": ts.format(1),
         "attachment": {"type": "prompt_snapshot", "prompt": "Which tests cover the auth callback?"}},
        {**base, "parentUuid": ids[11], "type": "assistant", "uuid": ids[4], "timestamp": ts.format(2), "requestId": "req_1", "apiBlockIndex": 0,
         "perTurnEffort": "medium",
         "message": {"model": "claude-haiku-4-5-20251001", "id": msg_id, "type": "message", "role": "assistant",
                     "content": [{"type": "thinking", "thinking": "look for callback tests", "signature": "sig"},
                                 {"type": "text", "text": "Let me search the test suite."}],
                     "stop_reason": None, "usage": {"input_tokens": 12, "output_tokens": 8}}},
        {**base, "parentUuid": ids[4], "type": "assistant", "uuid": ids[5], "timestamp": ts.format(3), "requestId": "req_1", "apiBlockIndex": 1,
         "message": {"model": "claude-haiku-4-5-20251001", "id": msg_id, "type": "message", "role": "assistant",
                     "content": [{"type": "tool_use", "id": "toolu_01", "name": "Grep", "input": {"pattern": "auth_callback", "path": "tests"}, "caller": {"type": "direct"}}],
                     "stop_reason": "tool_use", "usage": {"input_tokens": 12, "output_tokens": 20}}},
        {**base, "parentUuid": ids[5], "type": "user", "uuid": ids[6], "timestamp": ts.format(4), "sourceToolUseID": "toolu_01",
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_01", "content": "tests/test_auth.py:12:def test_auth_callback", "is_error": False}]},
         "toolUseResult": {"mode": "content", "numFiles": 1}},
        # an abandoned branch: a draft reply the user backed out of
        {**base, "parentUuid": ids[6], "type": "assistant", "uuid": ids[7], "timestamp": ts.format(5), "requestId": "req_x",
         "message": {"model": "claude-haiku-4-5-20251001", "id": "msg_x", "type": "message", "role": "assistant",
                     "content": [{"type": "text", "text": "DRAFT — never sent"}], "stop_reason": "end_turn", "usage": {}}},
        {**base, "parentUuid": ids[6], "type": "assistant", "uuid": ids[8], "timestamp": ts.format(6), "requestId": "req_2",
         "message": {"model": "claude-haiku-4-5-20251001", "id": "msg_2", "type": "message", "role": "assistant",
                     "content": [{"type": "text", "text": "One test covers it: tests/test_auth.py::test_auth_callback."}],
                     "stop_reason": "end_turn", "usage": {"input_tokens": 40, "output_tokens": 16}}},
        # a subagent's own tree
        {**base, "isSidechain": True, "parentUuid": None, "type": "user", "uuid": ids[9], "timestamp": ts.format(7),
         "message": {"role": "user", "content": "SIDECHAIN: explore the repo"}},
        {**base, "isSidechain": True, "parentUuid": ids[9], "type": "assistant", "uuid": ids[10], "timestamp": ts.format(8), "requestId": "req_s",
         "message": {"model": "claude-haiku-4-5-20251001", "id": "msg_s", "type": "message", "role": "assistant",
                     "content": [{"type": "text", "text": "SIDECHAIN reply"}], "stop_reason": "end_turn", "usage": {}}},
        {"type": "last-prompt", "lastPrompt": "Which tests cover the auth callback?", "leafUuid": ids[8], "sessionId": SESSION},
        {"type": "cost-state", "sessionId": SESSION, "totalCostUSD": 0.01, "modelUsage": {}, "startTime": 0},
        {"type": "ai-title", "aiTitle": "Auth callback tests", "sessionId": SESSION},
        {"type": "pr-link", "prNumber": 7, "prRepository": "acme/api", "prUrl": "https://example.invalid/pr/7", "sessionId": SESSION, "timestamp": ts.format(9)},
    ]


def _claude_fixture(path: Path, cwd: str = CWD) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in _claude_records(cwd)))
    return path


def _claude_compacted_fixture(path: Path, cwd: str = CWD) -> Path:
    """After compaction: a boundary with no parent, the summary the CLI
    carries, then new turns. The pre-compaction chain is still in the file."""
    old = _claude_records(cwd)
    ids = [str(uuid.uuid4()) for _ in range(4)]
    ts = "2026-09-12T11:00:{:02d}.000Z"
    base = {"isSidechain": False, "userType": "external", "cwd": cwd, "sessionId": SESSION, "version": "2.1.281", "gitBranch": "main"}
    old_leaf = next(r["leafUuid"] for r in old if r.get("type") == "last-prompt")
    new = [
        {**base, "parentUuid": None, "logicalParentUuid": old_leaf, "type": "system", "subtype": "compact_boundary", "uuid": ids[0],
         "timestamp": ts.format(0), "content": "Conversation compacted", "isMeta": True, "compactMetadata": {"trigger": "auto", "preTokens": 120000}},
        {**base, "parentUuid": ids[0], "type": "user", "uuid": ids[1], "timestamp": ts.format(1), "isCompactSummary": True,
         "message": {"role": "user", "content": "Summary: the auth callback is covered by one test."}},
        {**base, "parentUuid": ids[1], "type": "user", "uuid": ids[2], "timestamp": ts.format(2),
         "message": {"role": "user", "content": "Add a second test for the failure path."}},
        {**base, "parentUuid": ids[2], "type": "assistant", "uuid": ids[3], "timestamp": ts.format(3), "requestId": "req_3",
         "message": {"model": "claude-haiku-4-5-20251001", "id": "msg_3", "type": "message", "role": "assistant",
                     "content": [{"type": "text", "text": "Added tests/test_auth.py::test_auth_callback_failure."}], "stop_reason": "end_turn", "usage": {}}},
        {"type": "last-prompt", "lastPrompt": "Add a second test for the failure path.", "leafUuid": ids[3], "sessionId": SESSION},
    ]
    records = [r for r in old if r.get("type") != "last-prompt"] + new
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


CODEX_SID = "01a0a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"


def _codex_rows(cwd: str) -> list:
    turn = "01a0a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5c"
    sid = CODEX_SID
    return [
        ("session_meta", {"session_id": sid, "id": sid, "timestamp": "2026-09-12T10:00:00.000Z", "cwd": cwd, "originator": "codex_cli_rs",
                          "cli_version": "0.156.1", "source": "cli", "model_provider": "openai", "history_mode": "paginated",
                          "base_instructions": {"text": "You are Codex."}, "git": {"branch": "main"}, "runtime_workspace_roots": [cwd]}),
        ("event_msg", {"type": "task_started", "turn_id": turn, "root_turn_id": turn, "started_at": 1789200000, "model_context_window": 258400}),
        ("response_item", {"type": "message", "id": "msg_dev", "role": "developer", "content": [{"type": "input_text", "text": "# AGENTS.md instructions\nBe terse."}]}),
        ("response_item", {"type": "message", "id": "msg_env", "role": "user", "content": [{"type": "input_text", "text": f"<environment_context>\n  <cwd>{cwd}</cwd>\n</environment_context>"}]}),
        ("world_state", {"full": True, "state": {"agents_md": {"directory": cwd, "text": "Be terse."}}}),
        ("turn_context", {"turn_id": turn, "root_turn_id": turn, "cwd": cwd, "workspace_roots": [cwd], "model": "gpt-5-codex", "disabled_plugin_ids": []}),
        ("event_msg", {"type": "user_message", "message": "Which tests cover the auth callback?", "client_id": "c1"}),
        ("response_item", {"type": "message", "id": "msg_u1", "role": "user", "content": [{"type": "input_text", "text": "Which tests cover the auth callback?"}]}),
        ("event_msg", {"type": "item_completed", "turn_id": turn, "thread_id": sid, "item": {"type": "UserMessage", "id": "it1", "content": [{"type": "text", "text": "Which tests cover the auth callback?"}]}}),
        ("response_item", {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "gAAAAABopaque"}),
        ("event_msg", {"type": "agent_message", "message": "Let me search the test suite.", "phase": "commentary"}),
        ("response_item", {"type": "message", "id": "msg_a1", "role": "assistant", "content": [{"type": "output_text", "text": "Let me search the test suite."}], "phase": "commentary"}),
        ("response_item", {"type": "custom_tool_call", "id": "ctc_1", "status": "completed", "call_id": "call_1", "name": "exec", "input": "rg -n auth_callback tests"}),
        ("token_usage_record", {"thread_id": sid, "turn_id": turn, "usage": {"input_tokens": 300, "output_tokens": 20}}),
        ("response_item", {"type": "custom_tool_call_output", "id": "ctco_1", "call_id": "call_1", "output": [{"type": "input_text", "text": "tests/test_auth.py:12:def test_auth_callback"}], "metadata": {}}),
        ("event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 300, "output_tokens": 20, "total_tokens": 320}}}),
        ("event_msg", {"type": "agent_message", "message": "One test covers it: tests/test_auth.py::test_auth_callback.", "phase": "final_answer"}),
        ("response_item", {"type": "message", "id": "msg_a2", "role": "assistant", "content": [{"type": "output_text", "text": "One test covers it: tests/test_auth.py::test_auth_callback."}], "phase": "final_answer"}),
        ("event_msg", {"type": "item_completed", "turn_id": turn, "thread_id": sid, "item": {"type": "AgentMessage", "id": "it2", "content": [{"type": "Text", "text": "One test covers it: tests/test_auth.py::test_auth_callback."}]}}),
        ("event_msg", {"type": "task_complete", "turn_id": turn, "last_agent_message": "One test covers it.", "started_at": 1789200000, "completed_at": 1789200009}),
    ]


def _write_rollout(path: Path, rows: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = "2026-09-12T10:00:{:02d}.000Z"
    path.write_text("".join(json.dumps({"timestamp": t.format(i % 60), "ordinal": i, "type": kind, "payload": payload}) + "\n"
                            for i, (kind, payload) in enumerate(rows)))
    return path


def _codex_fixture(path: Path, cwd: str = CWD) -> Path:
    return _write_rollout(path, _codex_rows(cwd))


def _codex_compacted_fixture(path: Path, cwd: str = CWD) -> Path:
    """A window compaction: the model continues from replacement_history."""
    rows = _codex_rows(cwd)
    rows += [
        ("compacted", {"message": "Summary so far.", "window_number": 1, "replacement_history": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Summary so far: one test covers the callback."}]},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Understood."}]},
        ]}),
        ("event_msg", {"type": "context_compacted"}),
        ("response_item", {"type": "message", "id": "msg_u2", "role": "user", "content": [{"type": "input_text", "text": "Add a second test for the failure path."}]}),
        ("response_item", {"type": "message", "id": "msg_a3", "role": "assistant", "content": [{"type": "output_text", "text": "Added tests/test_auth.py::test_auth_callback_failure."}]}),
    ]
    return _write_rollout(path, rows)


def _store(harness: str, home: Path, cwd: str = CWD, **kw) -> ic.StoreRef:
    return ic.StoreRef(harness, home, Path(cwd), **kw)


def _claude_home(root: Path, cwd: str = CWD, *, compacted: bool = False) -> Path:
    home = root / "claude-home"
    fixture = _claude_compacted_fixture if compacted else _claude_fixture
    fixture(home / "projects" / claude_fmt.project_directory_name(Path(cwd)) / f"{SESSION}.jsonl", cwd=cwd)
    return home


def _codex_home(root: Path, cwd: str = CWD, *, compacted: bool = False) -> Path:
    home = root / "codex-home"
    fixture = _codex_compacted_fixture if compacted else _codex_fixture
    fixture(home / "sessions" / "2026" / "09" / "12" / f"rollout-2026-09-12T10-00-00-{CODEX_SID}.jsonl", cwd=cwd)
    return home


# ── the engine is what ships into a sandbox ─────────────────────────────────

class TestPackage:
    def test_imports_nothing_but_the_stdlib_and_itself(self):
        stdlib = set(sys.stdlib_module_names)
        # The one runtime dependency, and only as a guarded optional: the
        # modern SQLite the harness images install (sqlite_compat).
        optional = {"pysqlite3"}
        for path in PACKAGE.rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.level:
                        continue  # relative: the package itself
                    root = (node.module or "").split(".")[0]
                elif isinstance(node, ast.Import):
                    root = node.names[0].name.split(".")[0]
                else:
                    continue
                assert root in stdlib or root in optional, (
                    f"{path.relative_to(PACKAGE)} imports {root!r}: the engine must ship into a sandbox unchanged")

    def test_every_raised_reason_is_in_the_vocabulary(self):
        import re

        raised = set()
        for path in PACKAGE.rglob("*.py"):
            raised |= set(re.findall(r'InterchangeError\("([a-z_]+)"', path.read_text()))
        assert raised and raised <= set(ic.REASONS), raised - set(ic.REASONS)
        with pytest.raises(ValueError):
            ic.InterchangeError("not_a_reason")

    def test_formats_are_discoverable(self):
        described = {d["harness"]: d for d in ic.describe_formats()}
        assert set(described) == {"claude_code", "codex", "opencode", "hermes_agent", "openclaw"}
        assert "projects" in described["claude_code"]["store"] and "rollout" in described["codex"]["store"]
        assert "opencode.db" in described["opencode"]["store"] and "state.db" in described["hermes_agent"]["store"]
        assert "openclaw-agent.sqlite" in described["openclaw"]["store"]


# ── reading each harness's store ────────────────────────────────────────────

class TestClaudeCodeRead:
    def test_the_active_chain_is_the_thread(self, tmp_path):
        thread = ic.read_thread(_store("claude_code", _claude_home(tmp_path)))
        sk = ic.skeleton_of(thread)
        assert sk.roles == EXPECTED_ROLES and sk.tool_calls == 1 and sk.tool_results == 1 and sk.unpaired_tool_calls == 0
        texts = [e.text for e in thread.events if e.is_turn]
        assert texts == ["Which tests cover the auth callback?", "Let me search the test suite.",
                         "One test covers it: tests/test_auth.py::test_auth_callback."]
        assert (thread.session_id, thread.cwd, thread.cli_version, thread.model) == (SESSION, CWD, "2.1.281", "claude-haiku-4-5-20251001")
        # the draft branch and the subagent sidechain are not the thread
        assert "DRAFT" not in json.dumps([e.text for e in thread.events]) and "SIDECHAIN" not in json.dumps([e.text for e in thread.events])
        assert thread.dropped["opaque:inactive_branch_records"] == 3
        # bookkeeping inside the chain lands under accepted keys, with provenance
        assert thread.dropped["context:meta"] == 1 and thread.dropped["context:system_record"] == 1
        assert thread.dropped["opaque:record_attachment"] == 2 and thread.dropped["thinking"] == 1
        assert ic.classify_drops(dict(thread.dropped)) == {}
        call = next(e for e in thread.events if e.kind == ic.ir.TOOL_CALL)
        assert (call.tool_name, call.tool_call_id, call.tool_input) == ("Grep", "toolu_01", {"pattern": "auth_callback", "path": "tests"})
        assert str(call.provenance).startswith("record ") and "(assistant) block 0" in str(call.provenance)

    def test_a_compacted_session_starts_from_the_summary(self, tmp_path):
        thread = ic.read_thread(_store("claude_code", _claude_home(tmp_path, compacted=True)))
        turns = [(e.role, e.text) for e in thread.events if e.is_turn]
        assert turns == [("user", "Summary: the auth callback is covered by one test."),
                         ("user", "Add a second test for the failure path."),
                         ("assistant", "Added tests/test_auth.py::test_auth_callback_failure.")]
        assert thread.dropped["context:compact_boundary"] == 1
        assert ic.skeleton_of(thread).tool_calls == 0  # the pre-compaction chain is history the CLI already folded

    def test_locate_prefers_the_cwd_project_then_the_newest_anywhere(self, tmp_path):
        import time

        home = _claude_home(tmp_path)
        project = home / "projects" / claude_fmt.project_directory_name(Path(CWD))
        older = _claude_fixture(project / f"{uuid.uuid4()}.jsonl")
        os.utime(older, (time.time() - 3600, time.time() - 3600))
        _claude_fixture(home / "projects" / "-some-other-cwd" / "x.jsonl", cwd="/some/other/cwd")
        fmt = ic.format_for("claude_code")
        assert fmt.locate(_store("claude_code", home)) == str(project / f"{SESSION}.jsonl")
        assert fmt.locate(_store("claude_code", home, cwd="/elsewhere")).endswith("x.jsonl")
        assert fmt.locate(_store("claude_code", home, session_id=SESSION)) == str(project / f"{SESSION}.jsonl")
        with pytest.raises(ic.InterchangeError) as e:
            fmt.locate(_store("claude_code", tmp_path / "nohome"))
        assert e.value.reason == "source_empty"

    def test_project_directory_is_the_cwd_as_given(self):
        assert claude_fmt.project_directory_name(Path("/Users/casey/work/acme-api")) == "-Users-casey-work-acme-api"


class TestCodexRead:
    def test_the_response_items_are_the_thread(self, tmp_path):
        thread = ic.read_thread(_store("codex", _codex_home(tmp_path)))
        sk = ic.skeleton_of(thread)
        assert sk.roles == EXPECTED_ROLES and sk.tool_calls == 1 and sk.tool_results == 1 and sk.unpaired_tool_calls == 0
        assert (thread.session_id, thread.cwd, thread.cli_version, thread.model) == (CODEX_SID, CWD, "0.156.1", "gpt-5-codex")
        assert thread.dropped["context:injected"] == 1 and thread.dropped["context:system_message"] == 1
        assert thread.dropped["thinking"] == 1 and thread.dropped["context:turn_context"] == 1
        assert thread.dropped["opaque:record_world_state"] == 1 and thread.dropped["opaque:event_token_count"] == 1
        assert ic.classify_drops(dict(thread.dropped)) == {}
        call = next(e for e in thread.events if e.kind == ic.ir.TOOL_CALL)
        assert (call.tool_name, call.tool_call_id, call.tool_input) == ("exec", "call_1", "rg -n auth_callback tests")
        result = next(e for e in thread.events if e.kind == ic.ir.TOOL_RESULT)
        assert result.text == "tests/test_auth.py:12:def test_auth_callback"

    def test_a_compaction_window_replaces_what_came_before(self, tmp_path):
        thread = ic.read_thread(_store("codex", _codex_home(tmp_path, compacted=True)))
        turns = [(e.role, e.text) for e in thread.events if e.is_turn]
        assert turns == [("user", "Summary so far: one test covers the callback."), ("assistant", "Understood."),
                         ("user", "Add a second test for the failure path."), ("assistant", "Added tests/test_auth.py::test_auth_callback_failure.")]
        assert thread.dropped["compaction:windows"] == 1 and ic.skeleton_of(thread).tool_calls == 0

    def test_both_harnesses_read_to_the_same_skeleton(self, tmp_path):
        a = ic.skeleton_of(ic.read_thread(_store("claude_code", _claude_home(tmp_path))))
        b = ic.skeleton_of(ic.read_thread(_store("codex", _codex_home(tmp_path))))
        assert a.roles == b.roles and a.tool_calls == b.tool_calls  # texts differ only in the tool call's name/input


# ── writing each harness's store ────────────────────────────────────────────

class TestClaudeToCodex:
    def test_the_rollout_codex_resumes(self, tmp_path):
        thread = ic.read_thread(_store("claude_code", _claude_home(tmp_path)))
        home = tmp_path / ".codex"
        out = ic.translate(thread, _store("codex", home), ic.TargetIdentity(cli_version="0.156.1", model_provider="custom", model="gpt-5-codex"))
        assert out.fidelity.ok and out.native_path.is_relative_to(home / "sessions") and out.native_path.name.endswith(f"{out.session_id}.jsonl")
        rows = [json.loads(l) for l in out.native_path.read_text().splitlines()]
        head = rows[0]
        assert head["type"] == "session_meta" and set(head["payload"]) >= {"session_id", "id", "timestamp", "cwd", "originator", "cli_version", "source", "model_provider", "history_mode"}
        assert head["payload"]["model_provider"] == "custom" and head["payload"]["cli_version"] == "0.156.1" and head["payload"]["cwd"] == CWD
        items = [r["payload"] for r in rows if r["type"] == "response_item"]
        assert [i["type"] for i in items] == ["message", "message", "function_call", "function_call_output", "message"]
        assert items[0]["role"] == "user" and items[0]["content"] == [{"type": "input_text", "text": "Which tests cover the auth callback?"}]
        assert items[2]["name"] == "Grep" and items[2]["call_id"] == "toolu_01" and json.loads(items[2]["arguments"]) == {"pattern": "auth_callback", "path": "tests"}
        assert items[3] == {"type": "function_call_output", "call_id": "toolu_01", "output": "tests/test_auth.py:12:def test_auth_callback"}
        mirrors = [r["payload"] for r in rows if r["type"] == "event_msg"]
        assert [m["type"] for m in mirrors] == ["user_message", "agent_message", "agent_message"]
        assert "gAAAAAB" not in out.native_path.read_text() and "look for callback tests" not in out.native_path.read_text()
        assert out.fidelity.dropped["thinking"] == 1 and out.manifest_path.exists()
        manifest = json.loads(out.manifest_path.read_text())
        assert manifest["source"]["sha256"] == thread.sha256 and manifest["target"]["identity"]["model_provider"] == "custom"
        again = ic.skeleton_of(ic.format_for("codex").read(str(out.native_path)))
        assert again.digest == ic.skeleton_of(thread).digest


class TestCodexToClaude:
    def test_the_session_claude_continues(self, tmp_path):
        thread = ic.read_thread(_store("codex", _codex_home(tmp_path)))
        home = tmp_path / ".claude"
        out = ic.translate(thread, _store("claude_code", home), ic.TargetIdentity(cli_version="2.1.281", model="sonnet"))
        assert out.fidelity.ok
        assert out.native_path.parent == home / "projects" / claude_fmt.project_directory_name(Path(CWD)) and out.native_path.stem == out.session_id
        rows = [json.loads(l) for l in out.native_path.read_text().splitlines()]
        assert [r["type"] for r in rows] == ["user", "assistant", "assistant", "user", "assistant"]
        assert rows[0]["parentUuid"] is None and all(rows[i]["parentUuid"] == rows[i - 1]["uuid"] for i in range(1, len(rows)))
        assert {r["sessionId"] for r in rows} == {out.session_id} and {r["cwd"] for r in rows} == {CWD} and {r["version"] for r in rows} == {"2.1.281"}
        assert rows[0]["message"] == {"role": "user", "content": "Which tests cover the auth callback?"}
        assert rows[1]["message"]["model"] == "sonnet" and rows[1]["message"]["content"] == [{"type": "text", "text": "Let me search the test suite."}]
        assert rows[1]["message"]["stop_reason"] == "end_turn" and "usage" in rows[1]["message"] and rows[1]["requestId"]
        tool_use = rows[2]["message"]["content"][0]
        assert tool_use == {"type": "tool_use", "id": "call_1", "name": "exec", "input": {"input": "rg -n auth_callback tests"}}
        assert rows[3]["message"]["content"] == [{"type": "tool_result", "tool_use_id": "call_1", "content": "tests/test_auth.py:12:def test_auth_callback", "is_error": False}]
        assert out.fidelity.dropped["tool_call:non_object_input"] == 1  # the shell string is wrapped, not lost
        assert "gAAAAAB" not in out.native_path.read_text()
        again = ic.read_thread(_store("claude_code", home))
        assert ic.skeleton_of(again).digest == ic.skeleton_of(thread).digest


class TestVerdict:
    def test_a_structural_drop_fails_before_anything_is_written(self, tmp_path, monkeypatch):
        thread = ic.read_thread(_store("claude_code", _claude_home(tmp_path)))
        # a result whose call is missing: the reader would never pair it
        orphan = ic.Event(ic.ir.TOOL_RESULT, ic.Provenance(99, "user"), tool_call_id="toolu_ghost", text="?")
        thread.events.append(orphan)
        with pytest.raises(ic.InterchangeError) as e:
            ic.translate(thread, _store("codex", tmp_path / ".codex"))
        assert e.value.reason == "fidelity_drop" and "tool_result:orphan_id" in e.value.detail
        assert not (tmp_path / ".codex").exists()

    def test_a_readback_mismatch_discards_the_written_store(self, tmp_path, monkeypatch):
        thread = ic.read_thread(_store("claude_code", _claude_home(tmp_path)))
        fmt = ic.format_for("codex")
        real = fmt.read

        def lossy(ref):
            back = real(ref)
            back.events = [e for e in back.events if not (e.is_turn and e.role == "assistant")][:-0 or None]
            back.events = back.events[:-1]
            return back

        monkeypatch.setattr(fmt, "read", lossy)
        with pytest.raises(ic.InterchangeError) as e:
            ic.translate(thread, _store("codex", tmp_path / ".codex"))
        assert e.value.reason == "readback_mismatch"
        assert not list((tmp_path / ".codex").rglob("rollout-*.jsonl"))

    def test_empty_source_and_same_harness_are_refused(self, tmp_path):
        empty = ic.Thread("claude_code", "x", None, None, None, None, None, [], 0)
        with pytest.raises(ic.InterchangeError) as e:
            ic.translate(empty, _store("codex", tmp_path))
        assert e.value.reason == "empty_source"
        with pytest.raises(ic.InterchangeError) as e:
            ic.move_thread(_store("codex", tmp_path), _store("codex", tmp_path))
        assert e.value.reason == "same_harness"

    def test_accepted_versus_rejected_drops(self):
        assert ic.classify_drops({"opaque:event_token_count": 3, "thinking": 2, "context:injected": 1, "compaction:windows": 1,
                                  "tool_call:non_object_input": 1, "tool_call:missing_id": 1}) == {}
        assert ic.classify_drops({"tool_result:orphan_id": 1, "opaque:x": 2, "tool_call:missing_name": 0, "message:unsupported": 1}) \
            == {"tool_result:orphan_id": 1, "message:unsupported": 1}

    def test_install_needs_neither_hard_links_nor_fchmod(self, tmp_path, monkeypatch):
        """The hosted session volumes reject link(2) and fchmod(2) with EPERM
        (a real-sandbox move died exactly there); the install must land on
        such a filesystem, and never replace a thread the harness holds."""
        import errno

        def eperm(*a, **k):
            raise PermissionError(errno.EPERM, "Operation not permitted")

        monkeypatch.setattr(os, "link", eperm)
        monkeypatch.setattr(os, "fchmod", eperm)
        monkeypatch.setattr(os, "fsync", eperm)
        thread = ic.read_thread(_store("claude_code", _claude_home(tmp_path)))
        out = ic.translate(thread, _store("codex", tmp_path / ".codex"))
        assert out.fidelity.ok and out.manifest_path.exists()
        with pytest.raises(FileExistsError):
            formats.write_new_file(out.native_path, b"x")
        assert out.native_path.read_bytes() != b"x"


class TestMoveThread:
    def test_round_trip_through_the_runners_pointers(self, tmp_path):
        workdir = tmp_path / "work"
        workdir.mkdir()
        claude_home = _claude_home(tmp_path, cwd=str(workdir))
        codex_home = tmp_path / "codex-home"
        codex_pointer = workdir / ".noclick-codex-thread"
        out = ic.move_thread(_store("claude_code", claude_home, str(workdir)), _store("codex", codex_home, str(workdir), pointer=codex_pointer),
                             ic.TargetIdentity(cli_version="0.156.1", model_provider="openai"))
        assert out.fidelity.ok and codex_pointer.read_text() == out.session_id
        marker = workdir / ".noclick-turns"
        back = ic.move_thread(_store("codex", codex_home, str(workdir), pointer=codex_pointer),
                              _store("claude_code", tmp_path / "claude-home-2", str(workdir), pointer=marker))
        assert back.fidelity.ok and marker.read_text() == back.session_id
        assert back.native_path.parent == tmp_path / "claude-home-2" / "projects" / claude_fmt.project_directory_name(workdir)
        assert ic.skeleton_of(ic.read_thread(_store("claude_code", tmp_path / "claude-home-2", str(workdir)))).roles == EXPECTED_ROLES

    def test_nothing_to_move_is_source_empty(self, tmp_path):
        with pytest.raises(ic.InterchangeError) as e:
            ic.move_thread(_store("claude_code", tmp_path / "nohome"), _store("codex", tmp_path / "c"))
        assert e.value.reason == "source_empty" and "source_empty" in si.EXPECTED_FALLBACK_REASONS
        with pytest.raises(ic.InterchangeError) as e:
            ic.format_for("codex").locate(_store("codex", tmp_path / "codex", pointer=tmp_path / "missing"))
        assert e.value.reason == "source_empty"

    def test_a_harness_without_a_format_never_touches_the_source(self, tmp_path):
        with pytest.raises(ic.InterchangeError) as e:
            ic.move_thread(_store("codex", tmp_path), _store("some_future_harness", tmp_path / "h"))
        assert e.value.reason == "no_adapter" and not (tmp_path / "h").exists()

    def test_inspect_explains_a_store(self, tmp_path):
        report = ic.inspect_store(_store("claude_code", _claude_home(tmp_path)))
        assert report["skeleton"]["messages"] == 3 and report["turns_total"] == 3 and report["rejected_drops"] == {}
        assert report["turns"][0]["text"].startswith("Which tests") and "record" in report["turns"][0]["provenance"]


class TestCommand:
    """The engine runs as ``python -m …`` inside the target sandbox: one JSON
    verdict on stdout, whatever happened."""

    def _run(self, *args):
        proc = subprocess.run([sys.executable, "-m", "nodes.agent.interchange", *args], cwd=PACKAGE.parents[2],
                              capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, proc.stderr
        return ic.parse_verdict(proc.stdout)

    def test_move(self, tmp_path):
        workdir = tmp_path / "work"
        workdir.mkdir()
        home = _claude_home(tmp_path, cwd=str(workdir))
        pointer = tmp_path / "codex-home" / "sessions" / ".nc_thread"
        verdict = self._run("move", "--source-harness", "claude_code", "--source-home", str(home), "--source-cwd", str(workdir),
                            "--target-harness", "codex", "--target-home", str(tmp_path / "codex-home"), "--cwd", str(workdir),
                            "--target-pointer", str(pointer), "--target-cli-version", "0.156.1",
                            "--target-model-provider", "custom", "--target-model", "gpt-5-codex")
        assert verdict["ok"] and verdict["fidelity"]["ok"] and pointer.read_text() == verdict["session_id"]
        assert verdict["interchange_version"] == ic.INTERCHANGE_VERSION
        assert '"model_provider":"custom"' in Path(verdict["native_path"]).read_text()

    def test_inspect_and_formats(self, tmp_path):
        home = _claude_home(tmp_path)
        report = self._run("inspect", "--harness", "claude_code", "--home", str(home), "--cwd", CWD)
        assert report["ok"] and report["skeleton"]["messages"] == 3
        listing = self._run("formats")
        assert {f["harness"] for f in listing["formats"]} == set(ic.FORMATS)

    def test_failure_verdicts(self, tmp_path):
        verdict = self._run("move", "--source-harness", "claude_code", "--source-home", str(tmp_path / "none"),
                            "--target-harness", "codex", "--target-home", str(tmp_path / "codex-home"), "--cwd", str(tmp_path))
        assert verdict["ok"] is False and verdict["reason"] == "source_empty"
        assert ic.parse_verdict("chatter\n{not json\n" + json.dumps({"ok": False, "reason": "x", "detail": ""}) + "\n") == {"ok": False, "reason": "x", "detail": ""}
        assert ic.parse_verdict("Traceback …")["reason"] == "translator_crashed"


# ── the NoClick side ────────────────────────────────────────────────────────

class TestGlue:
    def test_harness_of(self):
        assert si.harness_of("claude-code") == "claude_code" and si.harness_of("codex") == "codex" and si.harness_of("hermes") == "hermes_agent"
        assert si.harness_of("gpt-5.6-luna") == si.SDK_HARNESS and si.harness_of(None) is None and si.harness_of("") is None

    def test_pair_support_follows_the_format_registry(self):
        assert si.pair_support("claude_code", "codex") is None and si.pair_support("codex", "claude_code") is None
        assert si.pair_support("codex", "codex") == ("same_harness", "")
        assert si.pair_support(si.SDK_HARNESS, "codex")[0] == "sdk_source"
        for source in ic.FORMATS:
            for target in ic.FORMATS:
                assert si.pair_support(source, target) == (("same_harness", "") if source == target else None), (source, target)
        assert si.pair_support("some_future_harness", "codex")[0] == "no_adapter"
        assert si.EXPECTED_FALLBACK_REASONS <= set(ic.REASONS)
        for reason in ("readback_mismatch", "fidelity_drop", "install_failed", "translator_crashed"):
            assert reason not in si.EXPECTED_FALLBACK_REASONS  # drift pages

    def test_target_identity_from_pins_and_config(self, tmp_path):
        ident = si.target_identity("codex", home=tmp_path, model="gpt-5-codex", custom_base_url=True)
        assert ident.model_provider == "custom" and ident.model == "gpt-5-codex" and ident.cli_version == si.harness_pins()["codex"]
        assert si.codex_model_provider(tmp_path) == "openai"
        (tmp_path / "config.toml").write_text('model_provider = "noclick"\nmodel = "x"\n')
        assert si.codex_model_provider(tmp_path) == "noclick"
        assert si.target_identity("claude_code", home=tmp_path, model="sonnet").model_provider is None


class TestSdkTarget:
    """The in-process agent has no harness store: a CLI thread continuing
    on it rides in as carried context, recorded as the known limit it is."""

    def test_pair_support_names_the_direction(self):
        assert si.pair_support("codex", "llm") == ("sdk_target", ic.REASONS["sdk_target"])
        assert si.pair_support("llm", "codex") == ("sdk_source", ic.REASONS["sdk_source"])
        assert "sdk_target" in si.EXPECTED_FALLBACK_REASONS

    async def test_carries_the_projection_and_reports_quietly(self, monkeypatch):
        import repositories.conversation as conv_mod
        import utils.database_pool as pool_mod

        events = [
            {"role": "user", "message": "remember the passphrase"},
            {"role": "assistant", "message": "noted"},
            {"role": "assistant", "message": "cancelled draft", "cancelled": True},
        ]

        class Repo:
            def __init__(self, pool):
                assert pool == "pool"

            async def read_events(self, conversation_id, user_id):
                assert (conversation_id, user_id) == ("ck:wf-1:agent_1:t", "u-1")
                return events

        reports = []

        async def report(pool, **kw):
            reports.append((pool, kw))

        monkeypatch.setattr(conv_mod, "ConversationRepo", Repo)
        monkeypatch.setattr(pool_mod, "get_native_pool", lambda: "pool")
        monkeypatch.setattr(si, "report_fallback", report)
        node = SimpleNamespace(_previous_agent_model="codex")
        block = await si.carry_into_sdk(node, conversation_id="ck:wf-1:agent_1:t", user_id="u-1")
        turns = ic.turns_from_projection(events)
        assert block == ic.carried_context(turns, reason="sdk_target") and "cancelled draft" not in block
        assert reports == [("pool", {
            "user_id": "u-1", "conversation_id": "ck:wf-1:agent_1:t", "source_harness": "codex", "target_harness": "llm",
            "reason": "sdk_target", "detail": ic.REASONS["sdk_target"], "versions": si.versions_for_report(),
        })]

    async def test_a_thread_already_on_the_sdk_carries_nothing(self, monkeypatch):
        called = []
        monkeypatch.setattr(si, "report_fallback", lambda *a, **k: called.append(1))
        for previous in (None, "openrouter/anthropic/claude-sonnet-5", "legacy/llm"):
            node = SimpleNamespace(_previous_agent_model=previous)
            assert await si.carry_into_sdk(node, conversation_id="c", user_id="u") == "", previous
        assert not called

    async def test_an_unreadable_projection_still_reports(self, monkeypatch):
        import utils.database_pool as pool_mod

        def boom():
            raise RuntimeError("no pool here")

        reports = []

        async def report(pool, **kw):
            reports.append((pool, kw["reason"]))

        monkeypatch.setattr(pool_mod, "get_native_pool", boom)
        monkeypatch.setattr(si, "report_fallback", report)
        node = SimpleNamespace(_previous_agent_model="claude-code")
        assert await si.carry_into_sdk(node, conversation_id="c", user_id="u") == ""
        assert reports == [(None, "sdk_target")]


class TestFallback:
    def test_carried_context_is_the_fenced_block_the_display_strips(self):
        block = ic.carried_context([(True, "first"), (False, "reply"), (True, "second")], reason="readback_mismatch")
        lines = block.split("\n")
        assert lines[0] == "<<<NOCLICK_CARRIED_CONTEXT" and lines[-1] == "NOCLICK_CARRIED_CONTEXT>>>"
        assert "different harness (readback_mismatch)" in lines[1]
        assert json.loads(lines[3]) == [{"isUser": True, "text": "first"}, {"isUser": False, "text": "reply"}, {"isUser": True, "text": "second"}]
        assert ic.with_carried_context("hi", "") == "hi" and ic.with_carried_context("hi", "<<<block>>>") == "hi\n\n<<<block>>>"

    def test_budget_trims_the_oldest_and_keeps_the_newest_tail(self):
        block = ic.carried_context([(True, "a" * 3000), (False, "b" * 3000), (True, "c" * 5000)], budget=4000)
        turns = json.loads(block.split("\n")[3])
        assert len(turns) == 1 and turns[0]["text"].startswith("… ") and turns[0]["text"].endswith("c" * 10) and len(turns[0]["text"]) == 4002
        assert ic.carried_context([(True, "   "), (False, "")]) == ""

    def test_projection_turns_skip_cancelled_and_non_messages(self):
        turns = ic.turns_from_projection([
            {"role": "user", "message": "hi", "trigger": {"node_type": "automation-slack"}},
            {"builder_prompt": {"prompt": "x"}},
            {"role": "assistant", "message": "err", "cancelled": True},
            {"role": "assistant", "message": "hello"},
        ])
        assert turns == [(True, "hi"), (False, "hello")]


@pytest.mark.asyncio
async def test_report_fallback_is_loud_for_drift_quiet_for_limits_and_never_raises(monkeypatch):
    seen = {}

    async def fake_feedback(pool, **kw):
        seen["feedback"] = kw

    class FakeRepo:
        def __init__(self, pool):
            pass

        async def set_metadata_key(self, conversation_id, key, value):
            seen["meta"] = (conversation_id, key, value)

    monkeypatch.setattr("utils.feedback.record_feedback", fake_feedback)
    monkeypatch.setattr("repositories.conversation.ConversationRepo", FakeRepo)
    await si.report_fallback(object(), user_id="u1", conversation_id="ck:wf:agent:thread", source_harness="claude_code",
                             target_harness="codex", reason="readback_mismatch", detail="lost a message", versions={"codex": "0.156.1"})
    assert seen["feedback"]["feedback_type"] == "interchange_fallback" and seen["feedback"]["dedupe_key"] == "claude_code:codex:readback_mismatch"
    assert seen["meta"][1] == "last_interchange" and seen["meta"][2]["ok"] is False
    seen.clear()
    await si.report_fallback(object(), user_id="u", conversation_id="c", source_harness="llm", target_harness="codex", reason="sdk_source")
    assert "feedback" not in seen and seen["meta"][2]["reason"] == "sdk_source"

    async def boom(pool, **kw):
        raise RuntimeError("slack down")

    monkeypatch.setattr("utils.feedback.record_feedback", boom)
    await si.report_fallback(object(), user_id="u1", conversation_id="c", source_harness="a", target_harness="b", reason="install_failed")  # swallowed


# ── the database-backed stores ──────────────────────────────────────────────
#
# Fixtures below reproduce the rows the pinned binaries write: opencode's
# message/part JSON (1.18), hermes's sessions/messages rows on its schema 26,
# openclaw's transcript_events + projection tables (2026.9.1, captured from a
# real store). Writers are validated by round trip here and against the real
# binaries in the Harness E2E.

import sqlite3

from nodes.agent.interchange.formats import hermes as hermes_fmt
from nodes.agent.interchange.formats import openclaw as openclaw_fmt
from nodes.agent.interchange.formats import opencode as opencode_fmt

OPENCLAW_TABLES = """CREATE TABLE conversations (conversation_id TEXT PRIMARY KEY) STRICT;
CREATE TABLE session_nodes (
  session_key TEXT NOT NULL PRIMARY KEY,
  current_session_id TEXT NOT NULL,
  entry_json TEXT NOT NULL,
  entry_valid INTEGER NOT NULL DEFAULT 0 CHECK (entry_valid IN (-1, 0, 1)),
  updated_at INTEGER NOT NULL,
  status TEXT CHECK (status IS NULL OR status IN ('running', 'done', 'failed', 'killed', 'timeout')),
  created_at INTEGER,
  created_via TEXT CHECK (created_via IS NULL OR created_via IN ('operator', 'spawn', 'channel', 'cron', 'talk', 'run', 'plugin', 'internal')),
  created_actor_type TEXT CHECK (created_actor_type IS NULL OR created_actor_type IN ('human', 'agent', 'system')),
  created_actor_id TEXT,
  owner_actor_type TEXT,
  owner_actor_id TEXT,
  owner_assigned_by_type TEXT,
  owner_assigned_by_id TEXT,
  owner_assigned_at INTEGER,
  project_id TEXT,
  parent_session_key TEXT,
  spawned_by TEXT,
  fork_source_session_key TEXT,
  fork_source_session_id TEXT,
  fork_source_entry_id TEXT,
  label TEXT,
  display_name TEXT,
  category TEXT,
  icon TEXT,
  pinned_at INTEGER,
  archived_at INTEGER,
  last_read_at INTEGER,
  last_interaction_at INTEGER,
  last_activity_at INTEGER
) STRICT;
CREATE TABLE session_windows (
  session_id TEXT NOT NULL PRIMARY KEY,
  session_key TEXT NOT NULL,
  previous_session_id TEXT,
  reason TEXT CHECK (reason IS NULL OR reason IN ('initial', 'reset', 'rollover', 'fork', 'rewind', 'switch', 'recovery', 'compaction')),
  session_scope TEXT NOT NULL DEFAULT 'conversation' CHECK (session_scope IN ('conversation', 'shared-main', 'group', 'channel')),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  transcript_updated_at INTEGER DEFAULT NULL,
  transcript_observed_at INTEGER DEFAULT NULL,
  session_entry_provenance INTEGER NOT NULL DEFAULT 0 CHECK (session_entry_provenance IN (0, 1)),
  acp_owned INTEGER NOT NULL DEFAULT 0 CHECK (acp_owned IN (0, 1)),
  plugin_owner_id TEXT,
  hook_external_content_source TEXT CHECK (hook_external_content_source IS NULL OR hook_external_content_source IN ('gmail', 'webhook')),
  started_at INTEGER,
  ended_at INTEGER,
  status TEXT CHECK (status IS NULL OR status IN ('running', 'done', 'failed', 'killed', 'timeout')),
  chat_type TEXT CHECK (chat_type IS NULL OR chat_type IN ('direct', 'group', 'channel')),
  channel TEXT,
  account_id TEXT,
  primary_conversation_id TEXT,
  model_provider TEXT,
  model TEXT,
  agent_harness_id TEXT,
  parent_session_key TEXT,
  spawned_by TEXT,
  display_name TEXT,
  FOREIGN KEY (session_key) REFERENCES session_nodes(session_key) ON DELETE CASCADE,
  FOREIGN KEY (primary_conversation_id) REFERENCES conversations(conversation_id) ON DELETE SET NULL
) STRICT;
CREATE TABLE transcript_events (
  session_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  event_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (session_id, seq),
  FOREIGN KEY (session_id) REFERENCES "session_windows"(session_id) ON DELETE CASCADE
) STRICT;
CREATE TABLE transcript_event_identities (
  session_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  event_type TEXT,
  parent_id TEXT,
  message_idempotency_key TEXT,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (session_id, event_id),
  FOREIGN KEY (session_id, seq) REFERENCES transcript_events(session_id, seq) ON DELETE CASCADE
) STRICT;
CREATE TABLE session_transcript_index_state (
  session_id TEXT NOT NULL PRIMARY KEY,
  indexed_seq INTEGER NOT NULL,
  leaf_event_id TEXT,
  needs_rebuild INTEGER NOT NULL DEFAULT 0,
  active_event_count INTEGER NOT NULL DEFAULT 0,
  active_message_count INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL,
  FOREIGN KEY (session_id) REFERENCES session_windows(session_id) ON DELETE CASCADE
) STRICT;
CREATE TABLE session_transcript_active_events (
  session_id TEXT NOT NULL,
  active_position INTEGER NOT NULL CHECK (active_position >= 0),
  event_seq INTEGER NOT NULL,
  message_position INTEGER CHECK (message_position IS NULL OR message_position >= 0),
  context_eligible INTEGER,
  PRIMARY KEY (session_id, active_position),
  FOREIGN KEY (session_id, event_seq) REFERENCES transcript_events(session_id, seq) ON DELETE CASCADE
) STRICT;
CREATE TABLE transcript_rewrite_watermarks (
  session_id TEXT NOT NULL PRIMARY KEY,
  generation TEXT NOT NULL,
  updated_at INTEGER NOT NULL,
  FOREIGN KEY (session_id) REFERENCES "session_windows"(session_id) ON DELETE CASCADE
) STRICT;
CREATE VIRTUAL TABLE session_transcript_fts USING fts5(
  text,
  session_id UNINDEXED,
  message_id UNINDEXED,
  role UNINDEXED,
  timestamp UNINDEXED,
  tokenize = 'unicode61 remove_diacritics 2'
);"""


def _opencode_home(root: Path, cwd: str = CWD) -> Path:
    """A 1.18-shaped opencode database: user text; assistant with step-start,
    reasoning, text, a completed tool part carrying its result, step-finish;
    a final assistant text. Ids and times as the CLI mints them."""
    home = root / "xdg"
    db = home / "opencode" / "opencode.db"
    db.parent.mkdir(parents=True)
    sid = "ses_01a09500000feTeSt0000000001"
    t = 1789200000000
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE project (id text PRIMARY KEY, worktree text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL, sandboxes text NOT NULL);
            CREATE TABLE session (id text PRIMARY KEY, project_id text NOT NULL, parent_id text, slug text NOT NULL, directory text NOT NULL, title text NOT NULL,
                version text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL, time_archived integer);
            CREATE TABLE message (id text PRIMARY KEY, session_id text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL);
            CREATE TABLE part (id text PRIMARY KEY, message_id text NOT NULL, session_id text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL);
        """)
        conn.execute("INSERT INTO project VALUES ('global', '/', ?, ?, '[]')", (t, t))
        conn.execute("INSERT INTO session VALUES (?, 'global', NULL, 'curious-panda', ?, 'Auth callback tests', '1.18.29', ?, ?, NULL)", (sid, cwd, t, t + 9000))
        u, a1, a2 = "msg_01a0950000010000000000u1", "msg_01a0950000020000000000a1", "msg_01a0950000030000000000a2"
        conn.execute("INSERT INTO message VALUES (?, ?, ?, ?, ?)", (u, sid, t + 1000, t + 1000, json.dumps(
            {"id": u, "sessionID": sid, "role": "user", "time": {"created": t + 1000}, "agent": "build", "model": {"providerID": "anthropic", "modelID": "claude-sonnet-4-5"}})))
        conn.execute("INSERT INTO message VALUES (?, ?, ?, ?, ?)", (a1, sid, t + 2000, t + 5000, json.dumps(
            {"id": a1, "sessionID": sid, "role": "assistant", "time": {"created": t + 2000, "completed": t + 5000}, "parentID": u, "modelID": "claude-sonnet-4-5",
             "providerID": "anthropic", "mode": "build", "agent": "build", "path": {"cwd": cwd, "root": "/"}, "cost": 0,
             "tokens": {"total": 10, "input": 8, "output": 2, "reasoning": 0, "cache": {"read": 0, "write": 0}}, "finish": "tool-calls"})))
        conn.execute("INSERT INTO message VALUES (?, ?, ?, ?, ?)", (a2, sid, t + 6000, t + 9000, json.dumps(
            {"id": a2, "sessionID": sid, "role": "assistant", "time": {"created": t + 6000, "completed": t + 9000}, "parentID": u, "modelID": "claude-sonnet-4-5",
             "providerID": "anthropic", "mode": "build", "agent": "build", "path": {"cwd": cwd, "root": "/"}, "cost": 0,
             "tokens": {"total": 12, "input": 8, "output": 4, "reasoning": 0, "cache": {"read": 0, "write": 0}}, "finish": "stop"})))
        parts = [
            (u, t + 1000, {"type": "text", "text": "Which tests cover the auth callback?"}),
            (a1, t + 2001, {"type": "step-start"}),
            (a1, t + 2002, {"type": "reasoning", "text": "look for callback tests", "time": {"start": t + 2002, "end": t + 2500}}),
            (a1, t + 2600, {"type": "text", "text": "Let me search the test suite.", "time": {"start": t + 2600, "end": t + 2600}}),
            (a1, t + 3000, {"type": "tool", "callID": "call_function_abc_1", "tool": "grep", "state": {"status": "completed", "input": {"pattern": "auth_callback", "path": "tests"},
                             "output": "tests/test_auth.py:12:def test_auth_callback", "title": "grep", "metadata": {}, "time": {"start": t + 3000, "end": t + 3100}}}),
            (a1, t + 5000, {"type": "step-finish", "reason": "tool-calls", "cost": 0, "tokens": {"total": 10, "input": 8, "output": 2, "reasoning": 0, "cache": {"read": 0, "write": 0}}}),
            (a2, t + 6001, {"type": "step-start"}),
            (a2, t + 6002, {"type": "text", "text": "One test covers it: tests/test_auth.py::test_auth_callback.", "time": {"start": t + 6002, "end": t + 6002}}),
            (a2, t + 9000, {"type": "step-finish", "reason": "stop", "cost": 0, "tokens": {"total": 12, "input": 8, "output": 4, "reasoning": 0, "cache": {"read": 0, "write": 0}}}),
        ]
        for i, (mid, at, data) in enumerate(parts):
            pid = f"prt_01a0950000{i:02d}00000000000p{i}"
            conn.execute("INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)", (pid, mid, sid, at, at, json.dumps({"id": pid, "sessionID": sid, "messageID": mid, **data})))
    return home


def _hermes_home(root: Path, cwd: str = CWD) -> Path:
    """A schema-26 hermes state database with the fixed NoClick session:
    user text, an assistant tool-call row, the tool row, the reply."""
    home = root / "hermes-home"
    home.mkdir()
    now = 1789200000.0
    with sqlite3.connect(home / "state.db") as conn:
        conn.executescript(hermes_fmt.SCHEMA_SQL)
        conn.execute("INSERT INTO schema_version (version) VALUES (26)")
        conn.execute("INSERT INTO sessions (id, source, model, started_at, cwd, title, message_count, tool_call_count) VALUES (?,?,?,?,?,?,?,?)",
                     ("noclick", "api", "anthropic/claude-sonnet-4-5", now, cwd, "Auth callback tests", 3, 1))
        rows = [("user", "Which tests cover the auth callback?", None, None, None, None, None, None),
                ("assistant", "Let me search the test suite.", None, json.dumps([{"id": "call_1", "type": "function", "function": {"name": "terminal", "arguments": json.dumps({"command": "rg -n auth_callback tests"})}}]),
                 None, "tool_calls", "**Searching**\n\nI should grep for the callback.", None),
                ("tool", "tests/test_auth.py:12:def test_auth_callback", "call_1", None, "terminal", None, None, None),
                ("assistant", "One test covers it: tests/test_auth.py::test_auth_callback.", None, None, None, "stop", None, None),
                # a rewound row the gateway soft-deleted: never part of the thread
                ("assistant", "DRAFT that was rewound", None, None, None, "stop", None, 0)]
        for i, (role, content, tcid, tcalls, tname, finish, reasoning, active) in enumerate(rows):
            conn.execute("INSERT INTO messages (session_id, role, content, tool_call_id, tool_calls, tool_name, timestamp, finish_reason, reasoning, active) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         ("noclick", role, content, tcid, tcalls, tname, now + i, finish, reasoning, 1 if active is None else active))
    return home


def _openclaw_state(root: Path, cwd: str = CWD, *, session_id: str = "noclick-abc123def456") -> Path:
    """A 2026.9.1 openclaw agent database holding one thread under NoClick's
    session key, with the projection rows the Gateway keeps beside the
    events, plus an abandoned event the active projection excludes."""
    state = root / "openclaw-state"
    db = state / "agents" / "main" / "agent" / "openclaw-agent.sqlite"
    db.parent.mkdir(parents=True)
    now = 1789200000000
    ids = [str(uuid.uuid4()) for _ in range(6)]
    events = [
        {"type": "session", "version": 3, "id": session_id, "timestamp": "2026-09-12T10:00:00.000Z", "cwd": cwd},
        {"type": "model_change", "id": ids[0], "parentId": None, "timestamp": "2026-09-12T10:00:00.100Z", "provider": "anthropic", "modelId": "claude-sonnet-4-5"},
        {"type": "custom", "customType": "model-snapshot", "data": {"timestamp": now, "provider": "anthropic", "modelApi": "anthropic-messages", "modelId": "claude-sonnet-4-5"},
         "id": ids[1], "parentId": ids[0], "timestamp": "2026-09-12T10:00:00.200Z"},
        {"type": "message", "id": ids[2], "parentId": ids[1], "timestamp": "2026-09-12T10:00:01.000Z",
         "message": {"role": "user", "content": "Which tests cover the auth callback?", "timestamp": now + 1000, "__openclaw": {"senderIsOwner": True}}},
        {"type": "message", "id": ids[3], "parentId": ids[2], "timestamp": "2026-09-12T10:00:02.000Z",
         "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "look"}, {"type": "text", "text": "Let me search the test suite."},
                                                       {"type": "toolCall", "id": "toolu_01", "name": "exec", "arguments": {"command": "rg -n auth_callback tests"}}],
                     "api": "anthropic-messages", "provider": "anthropic", "model": "claude-sonnet-4-5", "stopReason": "toolUse", "timestamp": now + 2000,
                     "usage": {"input": 1, "output": 1, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 2, "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}}},
        {"type": "message", "id": ids[4], "parentId": ids[3], "timestamp": "2026-09-12T10:00:03.000Z",
         "message": {"role": "toolResult", "toolCallId": "toolu_01", "toolName": "exec", "content": [{"type": "text", "text": "tests/test_auth.py:12:def test_auth_callback"}], "isError": False, "timestamp": now + 3000}},
        {"type": "message", "id": ids[5], "parentId": ids[4], "timestamp": "2026-09-12T10:00:04.000Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "One test covers it: tests/test_auth.py::test_auth_callback."}],
                     "api": "anthropic-messages", "provider": "anthropic", "model": "claude-sonnet-4-5", "stopReason": "stop", "timestamp": now + 4000,
                     "usage": {"input": 1, "output": 1, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 2, "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}}},
        {"type": "message", "id": str(uuid.uuid4()), "parentId": ids[4], "timestamp": "2026-09-12T10:00:05.000Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "ABANDONED branch"}], "api": "anthropic-messages", "provider": "anthropic", "model": "claude-sonnet-4-5", "stopReason": "stop", "timestamp": now + 5000}},
    ]
    with sqlite3.connect(db) as conn:
        conn.executescript(OPENCLAW_TABLES)
        key = openclaw_fmt.SESSION_KEY
        conn.execute("INSERT INTO session_nodes (session_key, current_session_id, entry_json, entry_valid, updated_at) VALUES (?,?,?,1,?)",
                     (key, session_id, json.dumps({"sessionId": session_id, "updatedAt": now + 4000, "sessionStartedAt": now}), now + 4000))
        conn.execute("INSERT INTO session_windows (session_id, session_key, created_at, updated_at, session_entry_provenance, model_provider, model, agent_harness_id) VALUES (?,?,?,?,1,?,?,'openclaw')",
                     (session_id, key, now, now + 4000, "anthropic", "claude-sonnet-4-5"))
        active_seqs = [1, 2, 3, 4, 5, 6]  # everything but the header and the abandoned branch (seq 7)
        for seq, e in enumerate(events):
            conn.execute("INSERT INTO transcript_events VALUES (?,?,?,?)", (session_id, seq, json.dumps(e), now))
            conn.execute("INSERT INTO transcript_event_identities (session_id, event_id, seq, event_type, parent_id, created_at) VALUES (?,?,?,?,?,?)",
                         (session_id, e.get("id") or session_id, seq, e["type"], e.get("parentId"), now))
        mp = 0
        for pos, seq in enumerate(active_seqs):
            is_msg = events[seq]["type"] == "message"
            conn.execute("INSERT INTO session_transcript_active_events VALUES (?,?,?,?,1)", (session_id, pos, seq, mp if is_msg else None))
            mp += is_msg
        conn.execute("INSERT INTO session_transcript_index_state VALUES (?,?,?,0,?,?,?)", (session_id, 6, ids[5], len(active_seqs), mp, now + 4000))
        conn.execute("INSERT INTO transcript_rewrite_watermarks VALUES (?,?,?)", (session_id, "abcd", now))
    return state


class TestOpenCodeStore:
    def test_reads_messages_and_pairs_the_tool_part(self, tmp_path):
        home = _opencode_home(tmp_path)
        thread = ic.read_thread(ic.StoreRef("opencode", home, Path(CWD)))
        sk = ic.skeleton_of(thread)
        assert sk.roles == EXPECTED_ROLES and sk.tool_calls == 1 and sk.tool_results == 1 and sk.unpaired_tool_calls == 0
        assert (thread.session_id, thread.cwd, thread.cli_version, thread.model) == ("ses_01a09500000feTeSt0000000001", CWD, "1.18.29", "claude-sonnet-4-5")
        call = next(e for e in thread.events if e.kind == ic.ir.TOOL_CALL)
        assert (call.tool_name, call.tool_call_id, call.tool_input) == ("grep", "call_function_abc_1", {"pattern": "auth_callback", "path": "tests"})
        assert thread.dropped["thinking"] == 1 and thread.dropped["opaque:part_step-start"] == 2 and ic.classify_drops(dict(thread.dropped)) == {}
        # the pointer names the session; a missing one is nothing to move
        pointer = tmp_path / ".noclick-opencode-session"
        pointer.write_text("ses_01a09500000feTeSt0000000001")
        assert ic.format_for("opencode").locate(ic.StoreRef("opencode", home, Path(CWD), pointer=pointer)).endswith("#ses_01a09500000feTeSt0000000001")
        pointer.write_text("ses_nope")
        with pytest.raises(ic.InterchangeError) as e:
            ic.format_for("opencode").locate(ic.StoreRef("opencode", home, Path(CWD), pointer=pointer))
        assert e.value.reason == "source_empty"

    def test_bundle_is_the_importers_shape(self, tmp_path):
        thread = ic.read_thread(_store("claude_code", _claude_home(tmp_path)))
        fmt = ic.format_for("opencode")
        written = fmt.write(thread, ic.StoreRef("opencode", tmp_path / "xdg", Path(CWD)), ic.TargetIdentity(cli_version="1.18.29", model="anthropic/claude-sonnet-4-5"))
        bundle = written.records[0]
        assert set(bundle) == {"info", "messages"} and bundle["info"]["id"] == written.session_id and bundle["info"]["directory"] == CWD
        assert bundle["info"]["version"] == "1.18.29" and bundle["info"]["title"] == "Which tests cover the auth callback?"
        roles = [m["info"]["role"] for m in bundle["messages"]]
        assert roles == ["user", "assistant"]  # one assistant message carries text, the tool part, and the reply
        assistant = bundle["messages"][1]
        assert assistant["info"]["parentID"] == bundle["messages"][0]["info"]["id"] and assistant["info"]["finish"] == "tool-calls"
        assert assistant["info"]["providerID"] == "anthropic" and assistant["info"]["modelID"] == "claude-sonnet-4-5"
        assert [p["type"] for p in assistant["parts"]] == ["step-start", "text", "tool", "text", "step-finish"]
        tool = assistant["parts"][2]
        assert (tool["callID"], tool["tool"], tool["state"]["status"], tool["state"]["input"], tool["state"]["output"]) == \
            ("toolu_01", "Grep", "completed", {"pattern": "auth_callback", "path": "tests"}, "tests/test_auth.py:12:def test_auth_callback")
        assert all(re.fullmatch(r"(ses|msg|prt)_[0-9a-f]{12}[0-9A-Za-z]{14}", x) for x in
                   [bundle["info"]["id"]] + [m["info"]["id"] for m in bundle["messages"]] + [p["id"] for m in bundle["messages"] for p in m["parts"]])
        assert written.dropped["thinking"] == 1 and ic.classify_drops(dict(written.dropped)) == {}

    def test_install_needs_the_cli(self, tmp_path, monkeypatch):
        thread = ic.read_thread(_store("claude_code", _claude_home(tmp_path)))
        monkeypatch.setattr("shutil.which", lambda *a, **k: None)
        with pytest.raises(ic.InterchangeError) as e:
            ic.translate(thread, ic.StoreRef("opencode", tmp_path / "xdg", Path(CWD)))
        assert e.value.reason == "install_failed" and "opencode is not on PATH" in e.value.detail

    @pytest.mark.skipif(not shutil.which("opencode"), reason="requires the opencode CLI")
    def test_round_trip_through_the_real_importer(self, tmp_path):
        thread = ic.read_thread(_store("claude_code", _claude_home(tmp_path)))
        home = tmp_path / "xdg"
        pointer = tmp_path / ".noclick-opencode-session"
        out = ic.move_thread(_store("claude_code", _claude_home(tmp_path / "again")), ic.StoreRef("opencode", home, Path(CWD), pointer=pointer, environ=dict(os.environ)),
                             ic.TargetIdentity(model="anthropic/claude-sonnet-4-5"))
        assert out.fidelity.ok and pointer.read_text() == out.session_id
        assert ic.skeleton_of(ic.read_thread(ic.StoreRef("opencode", home, Path(CWD), pointer=pointer))).digest == ic.skeleton_of(thread).digest


class TestHermesStore:
    def test_reads_the_active_rows_of_the_fixed_session(self, tmp_path):
        home = _hermes_home(tmp_path)
        thread = ic.read_thread(ic.StoreRef("hermes_agent", home, Path(CWD), session_id="noclick"))
        sk = ic.skeleton_of(thread)
        assert sk.roles == EXPECTED_ROLES and sk.tool_calls == 1 and sk.tool_results == 1 and sk.unpaired_tool_calls == 0
        assert "DRAFT" not in json.dumps([e.text for e in thread.events])  # active = 0 is a rewind
        call = next(e for e in thread.events if e.kind == ic.ir.TOOL_CALL)
        assert (call.tool_name, call.tool_call_id, call.tool_input) == ("terminal", "call_1", {"command": "rg -n auth_callback tests"})
        result = next(e for e in thread.events if e.kind == ic.ir.TOOL_RESULT)
        assert (result.tool_call_id, result.tool_name, result.text) == ("call_1", "terminal", "tests/test_auth.py:12:def test_auth_callback")
        assert thread.dropped["thinking"] == 1 and ic.classify_drops(dict(thread.dropped)) == {}
        with pytest.raises(ic.InterchangeError) as e:
            ic.format_for("hermes_agent").locate(ic.StoreRef("hermes_agent", home, Path(CWD), session_id="other"))
        assert e.value.reason == "source_empty"

    def test_writes_a_store_the_gateway_boots_on(self, tmp_path):
        thread = ic.read_thread(_store("claude_code", _claude_home(tmp_path)))
        home = tmp_path / "hermes-home"
        out = ic.translate(thread, ic.StoreRef("hermes_agent", home, Path(CWD), session_id="noclick"), ic.TargetIdentity(model="anthropic/claude-sonnet-4-5"))
        assert out.fidelity.ok and out.native_path == home / "state.db"
        with sqlite3.connect(out.native_path) as conn:
            assert conn.execute("SELECT version FROM schema_version").fetchone() == (hermes_fmt.SCHEMA_VERSION,)
            # message_count counts user/assistant rows the way hermes does — the tool-call row is one
            assert conn.execute("SELECT source, model, title, message_count, tool_call_count FROM sessions WHERE id = 'noclick'").fetchone() == \
                ("api", "anthropic/claude-sonnet-4-5", "Which tests cover the auth callback?", 4, 1)
            rows = conn.execute("SELECT role, content, tool_call_id, tool_calls, tool_name, finish_reason FROM messages WHERE session_id = 'noclick' AND active = 1 ORDER BY id").fetchall()
        assert [r[0] for r in rows] == ["user", "assistant", "assistant", "tool", "assistant"]
        assert rows[2][1] is None and json.loads(rows[2][3]) == [{"id": "toolu_01", "type": "function", "function": {"name": "Grep", "arguments": json.dumps({"pattern": "auth_callback", "path": "tests"})}}]
        assert rows[2][5] == "tool_calls" and rows[3][2:5] == ("toolu_01", None, "Grep") and rows[4][5] == "stop"
        # moving again retires the older thread under the fixed id; the verdict reads only the new one
        again = ic.translate(thread, ic.StoreRef("hermes_agent", home, Path(CWD), session_id="noclick"))
        assert again.fidelity.ok
        with sqlite3.connect(out.native_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = 'noclick' AND active = 1").fetchone() == (5,)
            assert conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = 'noclick' AND active = 0").fetchone() == (5,)

    def test_a_failed_verdict_restores_the_previous_thread(self, tmp_path, monkeypatch):
        home = _hermes_home(tmp_path)
        before = ic.read_thread(ic.StoreRef("hermes_agent", home, Path(CWD), session_id="noclick"))
        fmt = ic.format_for("hermes_agent")
        real = fmt.read
        monkeypatch.setattr(fmt, "read", lambda ref: (lambda t: (setattr(t, "events", t.events[:-1]), t)[1])(real(ref)))
        with pytest.raises(ic.InterchangeError) as e:
            ic.translate(ic.read_thread(_store("claude_code", _claude_home(tmp_path))), ic.StoreRef("hermes_agent", home, Path(CWD), session_id="noclick"))
        assert e.value.reason == "readback_mismatch"
        monkeypatch.setattr(fmt, "read", real)
        assert ic.skeleton_of(ic.read_thread(ic.StoreRef("hermes_agent", home, Path(CWD), session_id="noclick"))).digest == ic.skeleton_of(before).digest


class TestOpenClawStore:
    def test_reads_the_active_projection_under_noclicks_key(self, tmp_path):
        state = _openclaw_state(tmp_path)
        thread = ic.read_thread(ic.StoreRef("openclaw", state, Path(CWD), session_id="noclick-not-this-one"))  # falls through to the key
        sk = ic.skeleton_of(thread)
        assert sk.roles == EXPECTED_ROLES and sk.tool_calls == 1 and sk.tool_results == 1 and sk.unpaired_tool_calls == 0
        assert (thread.session_id, thread.cwd, thread.model) == ("noclick-abc123def456", CWD, "anthropic/claude-sonnet-4-5")
        assert "ABANDONED" not in json.dumps([e.text for e in thread.events]) and thread.dropped["opaque:inactive_branch"] == 1
        assert thread.dropped["thinking"] == 1 and thread.dropped["opaque:entry_model_change"] == 1 and ic.classify_drops(dict(thread.dropped)) == {}
        call = next(e for e in thread.events if e.kind == ic.ir.TOOL_CALL)
        assert (call.tool_name, call.tool_call_id, call.tool_input) == ("exec", "toolu_01", {"command": "rg -n auth_callback tests"})

    def test_an_unknown_assistant_block_is_a_drift_signal_not_bookkeeping(self, tmp_path):
        events = openclaw_fmt.OpenClawFormat._message_events(ic.Provenance(4, "message"), {"role": "assistant", "content": [{"type": "hologram", "data": 1}]}, None)
        assert events[0].kind == ic.ir.MESSAGE and events[0].role is None and events[0].reason == "unknown_block_hologram"
        assert ic.classify_drops(ic.ir.count_drops(events) | {"message:unknown_block_hologram": 1}) == {"message:unknown_block_hologram": 1}

    def test_writes_the_events_and_the_projection_the_gateway_requires(self, tmp_path):
        thread = ic.read_thread(_store("claude_code", _claude_home(tmp_path)))
        state = tmp_path / "openclaw-state"
        db = state / "agents" / "main" / "agent" / "openclaw-agent.sqlite"
        db.parent.mkdir(parents=True)
        with sqlite3.connect(db) as conn:
            conn.executescript(OPENCLAW_TABLES)  # the primed store; priming itself needs the binary
        sid = "noclick-0123456789abcdef"
        out = ic.translate(thread, ic.StoreRef("openclaw", state, Path(CWD), session_id=sid.upper()), ic.TargetIdentity(model="anthropic/claude-sonnet-4-5"))
        assert out.fidelity.ok and out.session_id == sid  # canonical: lowercase
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT current_session_id FROM session_nodes WHERE session_key = ?", (openclaw_fmt.SESSION_KEY,)).fetchone() == (sid,)
            assert conn.execute("SELECT session_key, model_provider, model, agent_harness_id, session_entry_provenance FROM session_windows WHERE session_id = ?", (sid,)).fetchone() \
                == (openclaw_fmt.SESSION_KEY, "anthropic", "claude-sonnet-4-5", "openclaw", 1)
            events = [json.loads(r[0]) for r in conn.execute("SELECT event_json FROM transcript_events WHERE session_id = ? ORDER BY seq", (sid,))]
            state_row = conn.execute("SELECT indexed_seq, leaf_event_id, needs_rebuild, active_event_count, active_message_count FROM session_transcript_index_state WHERE session_id = ?", (sid,)).fetchone()
            active = conn.execute("SELECT active_position, event_seq, message_position FROM session_transcript_active_events WHERE session_id = ? ORDER BY active_position", (sid,)).fetchall()
            fts = conn.execute("SELECT role, text FROM session_transcript_fts WHERE session_id = ?", (sid,)).fetchall()
            identities = conn.execute("SELECT COUNT(*) FROM transcript_event_identities WHERE session_id = ?", (sid,)).fetchone()
        assert events[0] == {"type": "session", "version": 3, "id": sid, "timestamp": thread.started_at, "cwd": CWD}
        roles = [e["message"]["role"] for e in events[1:]]
        assert roles == ["user", "assistant", "toolResult", "assistant"]
        assert all(events[i]["parentId"] == events[i - 1]["id"] for i in range(2, len(events))) and events[1]["parentId"] is None
        assert events[2]["message"]["content"] == [{"type": "text", "text": "Let me search the test suite."},
                                                    {"type": "toolCall", "id": "toolu_01", "name": "Grep", "arguments": {"pattern": "auth_callback", "path": "tests"}}]
        assert events[2]["message"]["stopReason"] == "toolUse" and events[2]["message"]["api"] == "anthropic-messages"
        assert events[3]["message"] == {"role": "toolResult", "toolCallId": "toolu_01", "toolName": "Grep", "content": [{"type": "text", "text": "tests/test_auth.py:12:def test_auth_callback"}],
                                        "isError": False, "timestamp": events[3]["message"]["timestamp"]}
        assert state_row == (len(events) - 1, events[-1]["id"], 0, len(events) - 1, 4) and identities == (len(events),)
        assert active == [(0, 1, 0), (1, 2, 1), (2, 3, 2), (3, 4, 3)] and sorted(r[0] for r in fts) == ["assistant", "assistant", "user"]

    def test_priming_needs_the_binary_and_is_isolated_from_the_real_config(self, tmp_path, monkeypatch):
        thread = ic.read_thread(_store("claude_code", _claude_home(tmp_path)))
        monkeypatch.setattr("shutil.which", lambda *a, **k: None)
        with pytest.raises(ic.InterchangeError) as e:
            ic.translate(thread, ic.StoreRef("openclaw", tmp_path / "state", Path(CWD), session_id="noclick-x"))
        assert e.value.reason == "install_failed" and "openclaw is not on PATH" in e.value.detail
        calls = []

        def fake_run(argv, cwd=None, env=None, **k):
            calls.append((argv, env))
            db = tmp_path / "state2" / "agents" / "main" / "agent" / "openclaw-agent.sqlite"
            db.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(db) as conn:
                conn.executescript(OPENCLAW_TABLES)
            return SimpleNamespace(returncode=1, stdout="", stderr="")

        monkeypatch.setattr("shutil.which", lambda *a, **k: "/usr/bin/openclaw")
        monkeypatch.setattr("subprocess.run", fake_run)
        out = ic.translate(thread, ic.StoreRef("openclaw", tmp_path / "state2", Path(CWD), session_id="noclick-y",
                                               environ={"PATH": "/usr/bin", "OPENAI_API_KEY": "real", "OPENAI_BASE_URL": "http://real"}))
        assert out.fidelity.ok
        argv, env = calls[0]
        assert argv[:2] == ["/usr/bin/openclaw", "agent"] and "--model" in argv and argv[argv.index("--model") + 1] == "nc-prime/nc-prime"
        assert "OPENAI_API_KEY" not in env and "OPENAI_BASE_URL" not in env
        assert json.loads(Path(env["OPENCLAW_CONFIG_PATH"]).read_text()).get("models") is None  # no provider the prime could reach


def test_every_format_has_a_validated_version_and_a_local_store():
    import importlib.util

    from nodes.agent.local_interchange import local_store

    spec = importlib.util.spec_from_file_location("drift", Path(__file__).with_name("test_session_interchange_drift.py"))
    drift = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drift)
    VALIDATED_HARNESS_VERSIONS = drift.VALIDATED_HARNESS_VERSIONS

    assert set(VALIDATED_HARNESS_VERSIONS) == set(ic.FORMATS)
    for harness in ic.FORMATS:
        assert local_store(harness, Path("/tmp/x"), {}, as_target=True) is not None, harness


class TestSqliteCompat:
    """The database stores need SQLite 3.37+ (OpenClaw's tables are STRICT);
    the harness sandboxes' Python links bullseye's 3.34, so the formats go
    through ``sqlite_compat``, which answers the stdlib module or the
    ``pysqlite3-binary`` wheel every harness image installs."""

    def test_the_module_in_use_handles_strict_tables(self):
        from nodes.agent.interchange.formats import sqlite_compat as sc

        mod = sc.module()
        assert mod.sqlite_version_info >= sc.MIN_SQLITE and mod.Error in sc.Error
        conn = sc.connect(":memory:")
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT NOT NULL) STRICT")
        conn.execute("CREATE VIRTUAL TABLE f USING fts5(body)")  # OpenClaw's transcript index

    def test_a_runtime_without_a_modern_sqlite_names_the_fix(self, monkeypatch):
        from nodes.agent.interchange.formats import sqlite_compat as sc

        old = SimpleNamespace(__name__="sqlite3", sqlite_version_info=(3, 34, 1), sqlite_version="3.34.1", Error=Exception)
        monkeypatch.setattr(sc, "_candidates", lambda: [old])
        monkeypatch.setattr(sc, "_module", None)
        with pytest.raises(RuntimeError, match=r"3\.34\.1.*pysqlite3-binary==" + re.escape(sc.PYSQLITE3_BINARY)):
            sc.module()

    def test_a_store_that_is_not_a_database_is_source_unreadable(self, tmp_path):
        (tmp_path / "state.db").write_bytes(b"not a database, and the harness cannot open it either")
        with pytest.raises(ic.InterchangeError) as e:
            ic.read_thread(ic.StoreRef("hermes_agent", tmp_path, Path(CWD), session_id="noclick"))
        assert e.value.reason == "source_unreadable" and "hermes_agent store at" in e.value.detail
