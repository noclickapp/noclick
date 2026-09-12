"""Native thread interchange between harnesses (nodes/agent/session_interchange).

A thread moves as the harness's own session files, and the verdict is what
the TARGET's reader sees after the write — the same skeleton of messages
and paired tool calls the source held. Fixtures are fictional threads in the
record shapes the pinned harnesses write today (Claude Code 2.1.26x with its
queue/attachment/last-prompt bookkeeping records; a paginated Codex rollout
with ordinals, custom tool calls and encrypted reasoning), so a translator
or harness bump that stops reading them fails here before it fails a user.
"""

import dataclasses
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from nodes.agent import session_interchange as si

SESSION = "6f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f"
CWD = "/home/casey/work/acme-api"


def _claude_fixture(path: Path, cwd: str = CWD) -> Path:
    """A four-turn Claude Code thread: prompt → thinking + text → a tool
    call → its result → the reply, wrapped in the bookkeeping records the
    2.1.26x CLI writes around a conversation."""
    ids = [str(uuid.uuid4()) for _ in range(6)]
    ts = "2026-09-12T10:00:0{}.000Z"
    base = {"isSidechain": False, "sessionId": SESSION, "cwd": cwd, "version": "2.1.261", "userType": "external"}
    records = [
        {"type": "queue-operation", "operation": "enqueue", "timestamp": ts.format(0), "sessionId": SESSION, "content": "Which tests cover the auth callback?"},
        {**base, "parentUuid": None, "type": "user", "uuid": ids[0], "timestamp": ts.format(1), "promptId": str(uuid.uuid4()),
         "message": {"role": "user", "content": "Which tests cover the auth callback?"}},
        {**base, "parentUuid": ids[0], "type": "attachment", "uuid": ids[1], "timestamp": ts.format(1),
         "attachment": {"type": "total_tokens_reminder", "text": "<total_tokens>1000 tokens left</total_tokens>"}},
        {**base, "parentUuid": ids[1], "type": "assistant", "uuid": ids[2], "timestamp": ts.format(2), "requestId": "req_1",
         "message": {"model": "claude-haiku-4-5-20251001", "id": "msg_1", "type": "message", "role": "assistant",
                     "content": [{"type": "thinking", "thinking": "look for callback tests", "signature": "sig"},
                                 {"type": "text", "text": "Let me search the test suite."}],
                     "stop_reason": None, "usage": {"input_tokens": 12, "output_tokens": 8}}},
        {**base, "parentUuid": ids[2], "type": "assistant", "uuid": ids[3], "timestamp": ts.format(3), "requestId": "req_1",
         "message": {"model": "claude-haiku-4-5-20251001", "id": "msg_1", "type": "message", "role": "assistant",
                     "content": [{"type": "tool_use", "id": "toolu_01", "name": "Grep", "input": {"pattern": "auth_callback", "path": "tests"}}],
                     "stop_reason": "tool_use", "usage": {"input_tokens": 12, "output_tokens": 20}}},
        {**base, "parentUuid": ids[3], "type": "user", "uuid": ids[4], "timestamp": ts.format(4),
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_01", "content": "tests/test_auth.py:12:def test_auth_callback"}]},
         "toolUseResult": {"mode": "content", "numFiles": 1}},
        {**base, "parentUuid": ids[4], "type": "assistant", "uuid": ids[5], "timestamp": ts.format(5), "requestId": "req_2",
         "message": {"model": "claude-haiku-4-5-20251001", "id": "msg_2", "type": "message", "role": "assistant",
                     "content": [{"type": "text", "text": "One test covers it: tests/test_auth.py::test_auth_callback."}],
                     "stop_reason": "end_turn", "usage": {"input_tokens": 40, "output_tokens": 16}}},
        {"type": "last-prompt", "lastPrompt": "Which tests cover the auth callback?", "leafUuid": ids[5], "sessionId": SESSION},
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def _codex_fixture(path: Path, cwd: str = CWD) -> Path:
    """The same thread as a paginated Codex rollout (0.15x): ordinals, a
    developer context message, world_state, a custom tool call with a string
    input and its output, encrypted reasoning, token accounting."""
    sid = "01a0a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
    turn = "01a0a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5c"
    t = "2026-09-12T10:00:{:02d}.000Z"
    rows = [
        ("session_meta", {"session_id": sid, "id": sid, "timestamp": t.format(0), "cwd": cwd, "originator": "codex_cli_rs", "cli_version": "0.153.4", "source": "cli", "model_provider": "openai"}),
        ("event_msg", {"type": "task_started", "turn_id": turn, "started_at": 1789200000, "model_context_window": 258400}),
        ("response_item", {"type": "message", "id": "msg_dev", "role": "developer", "content": [{"type": "input_text", "text": "# AGENTS.md instructions\nBe terse."}]}),
        ("world_state", {"full": True, "state": {"agents_md": {"directory": cwd, "text": "Be terse."}}}),
        ("turn_context", {"turn_id": turn, "root_turn_id": turn, "cwd": cwd, "workspace_roots": [cwd], "model": "gpt-5-codex"}),
        ("response_item", {"type": "message", "id": "msg_u1", "role": "user", "content": [{"type": "input_text", "text": "Which tests cover the auth callback?"}]}),
        ("response_item", {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "gAAAAABopaque"}),
        ("response_item", {"type": "message", "id": "msg_a1", "role": "assistant", "content": [{"type": "output_text", "text": "Let me search the test suite."}], "phase": "commentary"}),
        ("response_item", {"type": "custom_tool_call", "id": "ctc_1", "status": "completed", "call_id": "call_1", "name": "exec", "input": "rg -n auth_callback tests"}),
        ("token_usage_record", {"thread_id": sid, "turn_id": turn, "usage": {"input_tokens": 300, "output_tokens": 20}}),
        ("response_item", {"type": "custom_tool_call_output", "id": "ctco_1", "call_id": "call_1", "output": [{"type": "input_text", "text": "tests/test_auth.py:12:def test_auth_callback"}]}),
        ("event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 300, "output_tokens": 20, "total_tokens": 320}}}),
        ("response_item", {"type": "message", "id": "msg_a2", "role": "assistant", "content": [{"type": "output_text", "text": "One test covers it: tests/test_auth.py::test_auth_callback."}], "phase": "final_answer"}),
        ("event_msg", {"type": "task_complete", "turn_id": turn, "last_agent_message": "One test covers it.", "started_at": 1789200000, "completed_at": 1789200009}),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps({"timestamp": t.format(i), "ordinal": i, "type": kind, "payload": payload}) + "\n" for i, (kind, payload) in enumerate(rows)))
    return path


EXPECTED_ROLES = ["user", "assistant", "assistant"]  # the two assistant turns; the tool call is its own event


class TestSkeletonAndDrops:
    def test_claude_fixture_reads_to_the_expected_skeleton(self, tmp_path):
        session = si.load_native_session("claude_code", home=tmp_path, session_ref=str(_claude_fixture(tmp_path / "s.jsonl")))
        sk = si.skeleton_of(session)
        assert sk.roles == EXPECTED_ROLES and sk.tool_calls == 1 and sk.tool_results == 1 and sk.unpaired_tool_calls == 0

    def test_codex_fixture_reads_to_the_same_skeleton(self, tmp_path):
        session = si.load_native_session("codex", home=tmp_path, session_ref=str(_codex_fixture(tmp_path / "r.jsonl")))
        sk = si.skeleton_of(session)
        assert sk.roles == EXPECTED_ROLES and sk.tool_calls == 1 and sk.tool_results == 1 and sk.unpaired_tool_calls == 0

    def test_accepted_drops_are_bookkeeping_and_reasoning_only(self):
        assert si.classify_drops({"opaque:token_count": 3, "thinking": 2, "context:turn_context": 1, "session:title": 1,
                                  "tool_call:non_object_input": 1, "tool_result:is_error": 1, "timestamp:invalid": 1,
                                  "message:privileged_role": 1}) == {}
        assert si.classify_drops({"tool_result:orphan_id": 1, "opaque:x": 2, "tool_call:missing_name": 0}) == {"tool_result:orphan_id": 1}

    def test_unsupported_harness_is_named(self, tmp_path):
        with pytest.raises(si.InterchangeError) as e:
            si.load_native_session("openclaw", home=tmp_path, session_ref="x")
        assert e.value.reason == "unsupported_harness"


class TestTranslate:
    def test_claude_to_codex_lands_a_rollout_the_codex_reader_resumes(self, tmp_path):
        src = si.load_native_session("claude_code", home=tmp_path, session_ref=str(_claude_fixture(tmp_path / "s.jsonl")))
        home = tmp_path / ".codex"
        result = si.translate(src, target_harness="codex", target_home=home, cwd=Path(CWD))
        assert result.fidelity.ok
        assert result.native_path.is_relative_to(home / "sessions") and result.native_path.name.startswith("rollout-")
        assert result.manifest_path.exists()
        head = json.loads(result.native_path.read_text().splitlines()[0])
        assert head["type"] == "session_meta"
        again = si.load_native_session("codex", home=home, session_ref=str(result.native_path))
        assert si.skeleton_of(again).roles == EXPECTED_ROLES
        assert result.fidelity.dropped.get("thinking") == 1  # the one loss we accept, and it is counted

    def test_codex_to_claude_lands_under_the_cwd_project(self, tmp_path):
        src = si.load_native_session("codex", home=tmp_path, session_ref=str(_codex_fixture(tmp_path / "r.jsonl")))
        home = tmp_path / ".claude"
        result = si.translate(src, target_harness="claude_code", target_home=home, cwd=Path(CWD))
        assert result.fidelity.ok
        assert result.native_path.parent.parent == home / "projects"
        again = si.load_native_session("claude_code", home=home, session_ref=str(result.native_path))
        assert si.skeleton_of(again).tool_calls == 1 and si.skeleton_of(again).tool_results == 1
        text = result.native_path.read_text()
        assert "Which tests cover the auth callback?" in text and "test_auth_callback" in text
        assert "gAAAAABopaque" not in text  # provider-bound reasoning never crosses

    def test_a_rejected_drop_fails_before_anything_is_written(self, tmp_path, monkeypatch):
        from session_migrate import conversion

        src = si.load_native_session("claude_code", home=tmp_path, session_ref=str(_claude_fixture(tmp_path / "s.jsonl")))
        real = conversion.convert_session

        def lossy(session, options):
            art = real(session, options)
            return dataclasses.replace(art, dropped={**art.dropped, "tool_result:orphan_id": 1})

        monkeypatch.setattr(conversion, "convert_session", lossy)
        with pytest.raises(si.InterchangeError) as e:
            si.translate(src, target_harness="codex", target_home=tmp_path / ".codex", cwd=Path(CWD))
        assert e.value.reason == "fidelity_drop" and "orphan_id" in e.value.detail
        assert not (tmp_path / ".codex").exists()

    def test_a_readback_mismatch_discards_the_written_store(self, tmp_path, monkeypatch):
        src = si.load_native_session("claude_code", home=tmp_path, session_ref=str(_claude_fixture(tmp_path / "s.jsonl")))
        real_load = si.load_native_session
        calls = {"n": 0}

        def flaky(harness, **kw):
            calls["n"] += 1
            session = real_load(harness, **kw)
            if harness == "codex":  # the read-back: pretend the target lost a message
                return SimpleNamespace(events=session.events[:-1], source_format=session.source_format)
            return session

        monkeypatch.setattr(si, "load_native_session", flaky)
        with pytest.raises(si.InterchangeError) as e:
            si.translate(src, target_harness="codex", target_home=tmp_path / ".codex", cwd=Path(CWD))
        assert e.value.reason == "readback_mismatch"
        assert not list((tmp_path / ".codex").rglob("rollout-*.jsonl"))

    def test_empty_source_is_refused(self, tmp_path):
        empty = SimpleNamespace(events=(), source_format=SimpleNamespace(value="claude"))
        with pytest.raises(si.InterchangeError) as e:
            si.translate(empty, target_harness="codex", target_home=tmp_path, cwd=Path(CWD))
        assert e.value.reason == "empty_source"


class TestFallback:
    def test_carried_context_is_the_fenced_block_the_display_strips(self):
        block = si.carried_context([(True, "first"), (False, "reply"), (True, "second")], reason="readback_mismatch")
        lines = block.split("\n")
        assert lines[0] == "<<<NOCLICK_CARRIED_CONTEXT" and lines[-1] == "NOCLICK_CARRIED_CONTEXT>>>"
        assert "different harness (readback_mismatch)" in lines[1]
        assert json.loads(lines[3]) == [{"isUser": True, "text": "first"}, {"isUser": False, "text": "reply"}, {"isUser": True, "text": "second"}]

    def test_budget_trims_the_oldest_and_keeps_the_newest_tail(self):
        block = si.carried_context([(True, "a" * 3000), (False, "b" * 3000), (True, "c" * 5000)], budget=4000)
        turns = json.loads(block.split("\n")[3])
        assert len(turns) == 1 and turns[0]["text"].startswith("… ") and turns[0]["text"].endswith("c" * 10) and len(turns[0]["text"]) == 4002
        assert si.carried_context([(True, "   "), (False, "")]) == ""

    def test_projection_turns_skip_cancelled_and_non_messages(self):
        turns = si.turns_from_projection([
            {"role": "user", "message": "hi", "trigger": {"node_type": "automation-slack"}},
            {"builder_prompt": {"prompt": "x"}},
            {"role": "assistant", "message": "err", "cancelled": True},
            {"role": "assistant", "message": "hello"},
        ])
        assert turns == [(True, "hi"), (False, "hello")]


@pytest.mark.asyncio
async def test_report_fallback_is_loud_deduped_and_never_raises(monkeypatch):
    seen = {}

    async def fake_feedback(pool, **kw):
        seen["feedback"] = kw
        return True

    class FakeRepo:
        def __init__(self, pool):
            pass

        async def set_metadata_key(self, conversation_id, key, value):
            seen["meta"] = (conversation_id, key, value)

    monkeypatch.setattr("utils.feedback.record_feedback", fake_feedback)
    monkeypatch.setattr("repositories.conversation.ConversationRepo", FakeRepo)
    await si.report_fallback(object(), user_id="u1", conversation_id="ck:wf:agent:thread", source_harness="claude_code",
                             target_harness="codex", reason="readback_mismatch", detail="lost a message", versions={"codex": "0.153.4"})
    assert seen["feedback"]["feedback_type"] == "interchange_fallback"
    assert seen["feedback"]["dedupe_key"] == "claude_code:codex:readback_mismatch"
    assert seen["meta"][1] == "last_interchange" and seen["meta"][2]["ok"] is False

    async def boom(pool, **kw):
        raise RuntimeError("slack down")

    monkeypatch.setattr("utils.feedback.record_feedback", boom)
    await si.report_fallback(object(), user_id="u1", conversation_id="c", source_harness="a", target_harness="b", reason="x")  # swallowed


class TestHarnessOf:
    def test_wrapper_ids_name_their_harness_and_model_ids_name_the_sdk(self):
        assert si.harness_of("claude-code") == "claude_code"
        assert si.harness_of("codex") == "codex"
        assert si.harness_of("hermes") == "hermes_agent"
        assert si.harness_of("gpt-5.6-luna") == si.SDK_HARNESS
        assert si.harness_of(None) is None and si.harness_of("") is None


class TestPairSupport:
    def test_claude_and_codex_move_both_ways(self):
        pins = si.harness_pins()
        assert si.pair_support("claude_code", "codex", pins=pins) is None
        assert si.pair_support("codex", "claude_code", pins=pins) is None

    def test_known_limits_are_named(self):
        assert si.pair_support("codex", "codex") == ("same_harness", "")
        assert si.pair_support(si.SDK_HARNESS, "codex")[0] == "sdk_source"
        assert si.pair_support("openclaw", "codex")[0] == "no_adapter"
        assert si.pair_support("codex", "hermes_agent")[0] == "unaddressable"
        assert si.pair_support("opencode", "codex", pins={"opencode": "0.0.1"})[0] == "translator_pin_mismatch"
        assert si.pair_support("opencode", "codex") is None  # the in-sandbox script trusts the backend's judgement
        for reason in ("no_adapter", "unaddressable", "sdk_source", "source_empty"):
            assert reason in si.EXPECTED_FALLBACK_REASONS
        assert "translator_pin_mismatch" not in si.EXPECTED_FALLBACK_REASONS  # a lag we must fix, so it pages


def _claude_home(tmp_path, workdir):
    from session_migrate.formats.claude import project_directory_name

    home = tmp_path / "claude-home"
    _claude_fixture(home / "projects" / project_directory_name(workdir) / f"{SESSION}.jsonl", cwd=str(workdir))
    return home


class TestMoveThread:
    def test_claude_to_codex_and_back_through_the_runners_pointers(self, tmp_path):
        workdir = tmp_path / "work"
        workdir.mkdir()
        claude_home = _claude_home(tmp_path, workdir)
        codex_home = tmp_path / "codex-home"
        codex_pointer = workdir / ".noclick-codex-thread"
        out = si.move_thread(
            si.StoreRef("claude_code", claude_home, workdir),
            si.StoreRef("codex", codex_home, workdir, pointer=codex_pointer),
            target_cli_version="0.153.4",
        )
        assert out.fidelity.ok and codex_pointer.read_text() == out.session_id
        assert out.native_path.name.endswith(f"{out.session_id}.jsonl")
        # Back: the codex source is found through the pointer the runner resumes by;
        # the claude target lands under the workdir's project and arms --continue.
        claude_home2 = tmp_path / "claude-home-2"
        marker = workdir / ".noclick-turns"
        back = si.move_thread(
            si.StoreRef("codex", codex_home, workdir, pointer=codex_pointer),
            si.StoreRef("claude_code", claude_home2, workdir, pointer=marker),
        )
        assert back.fidelity.ok and marker.read_text() == back.session_id
        from session_migrate.formats.claude import project_directory_name

        assert back.native_path.parent == claude_home2 / "projects" / project_directory_name(workdir)
        assert si.skeleton_of(si.load_native_session("claude_code", home=claude_home2, session_ref=str(back.native_path))).roles == EXPECTED_ROLES

    def test_claude_source_prefers_the_cwd_project_and_the_newest_thread(self, tmp_path):
        import os
        import time

        workdir = tmp_path / "work"
        workdir.mkdir()
        home = _claude_home(tmp_path, workdir)
        from session_migrate.formats.claude import project_directory_name

        project = home / "projects" / project_directory_name(workdir)
        older = _claude_fixture(project / "older.jsonl", cwd=str(workdir))
        os.utime(older, (time.time() - 3600, time.time() - 3600))
        _claude_fixture(home / "projects" / "-some-other-cwd" / "x.jsonl", cwd="/some/other/cwd")
        assert si.locate_source(si.StoreRef("claude_code", home, workdir)) == str(project / f"{SESSION}.jsonl")
        assert si.locate_source(si.StoreRef("claude_code", home, tmp_path / "elsewhere")).endswith("x.jsonl")  # no project for that cwd: newest anywhere

    def test_nothing_to_move_is_source_empty_not_a_failure(self, tmp_path):
        with pytest.raises(si.InterchangeError) as e:
            si.move_thread(si.StoreRef("claude_code", tmp_path / "nohome", tmp_path), si.StoreRef("codex", tmp_path / "c", tmp_path))
        assert e.value.reason == "source_empty" and "source_empty" in si.EXPECTED_FALLBACK_REASONS
        with pytest.raises(si.InterchangeError) as e:
            si.locate_source(si.StoreRef("codex", tmp_path / "codex", tmp_path, pointer=tmp_path / "missing"))
        assert e.value.reason == "source_empty"

    def test_a_blocked_pair_never_touches_the_target(self, tmp_path):
        with pytest.raises(si.InterchangeError) as e:
            si.move_thread(si.StoreRef("codex", tmp_path, tmp_path), si.StoreRef("hermes_agent", tmp_path / "h", tmp_path))
        assert e.value.reason == "unaddressable" and not (tmp_path / "h").exists()


class TestSandboxScript:
    """The engine runs as a plain script inside the target sandbox: one JSON
    verdict on stdout, whatever happened."""

    def _run(self, *args):
        import subprocess
        import sys

        script = Path(si.__file__)
        proc = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, proc.stderr
        return si.parse_verdict(proc.stdout)

    def test_move_verdict(self, tmp_path):
        workdir = tmp_path / "work"
        workdir.mkdir()
        home = _claude_home(tmp_path, workdir)
        pointer = tmp_path / "codex-home" / "sessions" / ".nc_thread"
        verdict = self._run(
            "--source-harness", "claude_code", "--source-home", str(home), "--source-cwd", str(workdir),
            "--target-harness", "codex", "--target-home", str(tmp_path / "codex-home"), "--cwd", str(workdir),
            "--target-pointer", str(pointer), "--target-cli-version", "0.153.4",
        )
        assert verdict["ok"] and verdict["fidelity"]["ok"] and pointer.read_text() == verdict["session_id"]
        assert verdict["translator_version"] == si.TRANSLATOR_VERSION

    def test_failure_verdicts(self, tmp_path):
        verdict = self._run(
            "--source-harness", "claude_code", "--source-home", str(tmp_path / "none"),
            "--target-harness", "codex", "--target-home", str(tmp_path / "codex-home"), "--cwd", str(tmp_path),
        )
        assert verdict == {"ok": False, "reason": "source_empty", "detail": verdict["detail"]}
        assert si.parse_verdict("chatter\n{not json\n" + json.dumps({"ok": False, "reason": "x", "detail": ""}) + "\n") == {"ok": False, "reason": "x", "detail": ""}
        assert si.parse_verdict("Traceback …")["reason"] == "translator_crashed"

    def test_script_imports_nothing_from_the_backend_at_module_level(self):
        import ast

        tree = ast.parse(Path(si.__file__).read_text())
        top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        names = {(n.module if isinstance(n, ast.ImportFrom) else n.names[0].name) for n in top_level}
        assert not {n for n in names if n and n.split(".")[0] in ("nodes", "utils", "repositories", "cloud", "session_migrate")}, names


def test_with_carried_context_keeps_the_users_words_first():
    assert si.with_carried_context("hi", "") == "hi"
    assert si.with_carried_context("hi", "<<<block>>>") == "hi\n\n<<<block>>>"


@pytest.mark.asyncio
async def test_expected_fallbacks_are_recorded_quietly(monkeypatch):
    seen = {}

    async def fake_feedback(pool, **kw):
        seen["feedback"] = kw

    class FakeRepo:
        def __init__(self, pool):
            pass

        async def set_metadata_key(self, conversation_id, key, value):
            seen["meta"] = value

    monkeypatch.setattr("utils.feedback.record_feedback", fake_feedback)
    monkeypatch.setattr("repositories.conversation.ConversationRepo", FakeRepo)
    await si.report_fallback(object(), user_id="u", conversation_id="c", source_harness="llm", target_harness="codex", reason="sdk_source")
    assert "feedback" not in seen and seen["meta"]["reason"] == "sdk_source"
    await si.report_fallback(object(), user_id="u", conversation_id="c", source_harness="codex", target_harness="claude_code", reason="convert_failed")
    assert seen["feedback"]["dedupe_key"] == "codex:claude_code:convert_failed"
