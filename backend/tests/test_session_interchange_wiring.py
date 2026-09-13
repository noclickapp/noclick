"""The thread interchange is wired into the runtime that ships everywhere.

``AgentNode`` captures the harness that ran the thread's last turn before the
user turn re-stamps the row; the local edition moves the thread in-process on
the operator's stores before the harness process starts, and a carried block
rides the first prompt only. The hosted wiring (sandbox volumes, the daemon
launcher, delivery) is covered in ``cloud/tests/test_session_interchange_hosted.py``.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nodes.agent import local_interchange as local
from nodes.agent import session_interchange as si

BACKEND = Path(__file__).resolve().parents[1]

# asyncio_mode = auto (pytest.ini)


def _node(previous=None, **over):
    return SimpleNamespace(
        workflow_id="wf-1", node_id="agent_1", user_id="u-1", conversation_id="ck:wf-1:agent_1:thread",
        chat_routing_id=lambda: "ck:wf-1:agent_1:thread", _previous_agent_model=previous, **over,
    )


# ── the agent node captures the previous harness before re-stamping the row ──

def test_previous_harness_is_read_before_the_user_turn_persists():
    source = (BACKEND / "nodes" / "agent_node.py").read_text()
    read_at = source.index("self._previous_agent_model = (")
    persist_at = source.index("persist_user_turn = asyncio.create_task(")
    assert read_at < persist_at, "the user-turn persist re-stamps agent_model before it is read"
    assert "COALESCE(EXCLUDED.agent_model, conversations.agent_model)" in source  # the lock follows the harness that ran


async def test_locked_model_read_never_blocks_a_turn(monkeypatch):
    from nodes.agent_node import AgentNode

    class Repo:
        def __init__(self, pool):
            pass

        async def get_agent_model(self, conversation_id):
            return "claude-code"

    monkeypatch.setattr("repositories.conversation.ConversationRepo", Repo)
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: object())
    assert await AgentNode._locked_agent_model(SimpleNamespace(), "c") == "claude-code"
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: (_ for _ in ()).throw(RuntimeError("no pool")))
    assert await AgentNode._locked_agent_model(SimpleNamespace(), "c") is None


# ── local edition ───────────────────────────────────────────────────────────

class TestLocalStores:
    def test_target_homes_follow_the_process_env_and_sources_are_inferred(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        workdir = tmp_path / "work"
        (workdir / ".codex" / "sessions").mkdir(parents=True)
        env = {"CODEX_HOME": str(workdir / ".codex"), "CLAUDE_CONFIG_DIR": str(workdir / ".claude")}
        assert local.local_store("codex", workdir, env, as_target=True).home == workdir / ".codex"
        assert local.local_store("codex", workdir, {}, as_target=True).home == tmp_path / "home" / ".codex"
        assert local.local_store("codex", workdir, {}, as_target=False).home == workdir / ".codex"  # a sign-in left it here
        assert local.local_store("claude_code", workdir, {}, as_target=False).home == tmp_path / "home" / ".claude"
        claude = local.local_store("claude_code", workdir, env, as_target=True)
        assert claude.home == workdir / ".claude" and claude.pointer == workdir / ".noclick-turns"
        for other in ("opencode", "hermes_agent", "openclaw"):
            assert local.local_store(other, workdir, {}, as_target=True) is None


class TestInterchangeLocal:
    async def test_moves_the_thread_before_the_process_starts(self, tmp_path, monkeypatch):
        import sys

        sys.path.insert(1, str(BACKEND / "tests"))
        from test_session_interchange import SESSION, _claude_fixture
        from nodes.agent.interchange.formats.claude_code import project_directory_name

        workdir = tmp_path / "work"
        workdir.mkdir()
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        _claude_fixture(home / ".claude" / "projects" / project_directory_name(workdir) / f"{SESSION}.jsonl", cwd=str(workdir))
        recorded = AsyncMock()
        monkeypatch.setattr(local, "record_native_move", recorded)
        monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: object())
        env = {"CODEX_HOME": str(workdir / ".codex")}
        block = await local.interchange_local(_node("claude-code"), "codex", workdir, env, conversation_id="c", user_id="u-1")
        assert block == ""
        pointer = (workdir / ".noclick-codex-thread").read_text()
        assert list((workdir / ".codex" / "sessions").glob(f"*/*/*/rollout-*-{pointer}.jsonl"))
        assert recorded.await_args.kwargs["result"]["session_id"] == pointer

    async def test_no_switch_touches_nothing(self, tmp_path):
        assert await local.interchange_local(_node(None), "codex", tmp_path, {}, conversation_id="c", user_id="u") == ""
        assert await local.interchange_local(_node("codex"), "codex", tmp_path, {}, conversation_id="c", user_id="u") == ""

    async def test_fallback_carries_the_projection_and_reports(self, tmp_path, monkeypatch):
        reported = AsyncMock()
        monkeypatch.setattr(local, "report_fallback", reported)
        monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: object())
        monkeypatch.setattr("repositories.conversation.ConversationRepo", lambda pool: SimpleNamespace(
            read_events=AsyncMock(return_value=[{"role": "user", "message": "we agreed on blue"}])))
        block = await local.interchange_local(_node("opencode"), "codex", tmp_path, {}, conversation_id="c", user_id="u-1")
        assert "we agreed on blue" in block and "(no_adapter)" in block
        assert reported.await_args.kwargs["reason"] == "no_adapter"
        # Nothing to move: the target's own store is the latest, nothing carried.
        monkeypatch.setenv("HOME", str(tmp_path))
        block = await local.interchange_local(_node("claude-code"), "codex", tmp_path / "w", {}, conversation_id="c", user_id="u-1")
        assert block == "" and reported.await_args.kwargs["reason"] == "source_empty"


def test_compose_prompt_puts_the_block_after_the_message_and_before_the_note():
    from nodes.agent.local_harness import _compose_prompt

    config = SimpleNamespace(message="hi", system_prompt="")
    assert _compose_prompt(config, inline_system=True, extra_note="tools", carried="<<<B>>>") == "hi\n\n<<<B>>>\n\n[Environment note: tools]"
    assert _compose_prompt(config, inline_system=True) == "hi"
