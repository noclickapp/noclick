"""Local-process CLI harness runner (open edition) — contract tests.

Pins: registry fallback wiring (the local runner claims
claude_code/codex/opencode), the
turn-scoped MCP tool endpoint (initialize/list/call + audit), per-harness
command assembly, output parsing, and a full fake-binary turn through
run_local_harness_turn.
"""

import asyncio
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import nodes.agent.local_harness as lh
from nodes.agent.local_harness import (
    _ToolSession,
    _build_command,
    _parse_output,
    _register_session,
    run_local_harness_turn,
    router,
)


class FakeConfig(SimpleNamespace):
    pass


def _config(**kw):
    defaults = dict(
        message="do the thing", system_prompt="", conversation_key=None,
        claude_code_model="", codex_model="", opencode_model="",
    )
    defaults.update(kw)
    return FakeConfig(**defaults)


# ── Registry fallback ────────────────────────────────────────────────────


def test_registry_uses_local_runner_by_default():
    import nodes.agent.harness_registry as registry

    registry.clear()
    try:
        assert registry.get_cli_turn_runner("claude_code") is run_local_harness_turn
        assert registry.get_cli_turn_runner("codex") is run_local_harness_turn
        assert registry.get_cli_turn_runner("opencode") is run_local_harness_turn
        # All five harnesses run locally (hermes + openclaw via their own
        # one-shot modes; see the adapter tests below).
        assert registry.get_cli_turn_runner("openclaw") is run_local_harness_turn
        assert registry.get_cli_turn_runner("hermes_agent") is run_local_harness_turn
    finally:
        registry.clear()


# ── MCP tool endpoint ────────────────────────────────────────────────────


@pytest.fixture
def mcp_client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_mcp_endpoint_serves_turn_tools(mcp_client, monkeypatch):
    calls = []

    async def fake_execute_tool(node, tool_name, arguments, tool_configs):
        calls.append((tool_name, arguments))
        return {"success": True, "data": {"echo": arguments}}

    audits = []
    monkeypatch.setattr("nodes.agent.tool_execution.execute_tool", fake_execute_tool)
    monkeypatch.setattr(
        "utils.tool_call_log.record_tool_call",
        lambda **kw: audits.append(kw),
    )

    token = _register_session(_ToolSession(
        node=SimpleNamespace(workflow_id="wf1"),
        tool_configs={
            "linear__create_issue": {
                "tool_type": "node_op",
                "_description": "Create a Linear issue",
                "_parameters": {"type": "object", "properties": {"title": {"type": "string"}}},
                "node_id": "n-linear", "operation": "create_issue",
            },
        },
        user_id="u1", conversation_id="local:agent:ck",
    ))
    try:
        r = mcp_client.post(f"/local-agent-mcp/{token}", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        })
        assert r.json()["result"]["serverInfo"]["name"] == "noclick-local-agent"

        r = mcp_client.post(f"/local-agent-mcp/{token}", json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list",
        })
        tools = r.json()["result"]["tools"]
        assert tools == [{
            "name": "linear__create_issue",
            "description": "Create a Linear issue",
            "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}}},
        }]

        r = mcp_client.post(f"/local-agent-mcp/{token}", json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "linear__create_issue", "arguments": {"title": "T"}},
        })
        payload = r.json()["result"]
        assert payload["isError"] is False
        assert json.loads(payload["content"][0]["text"])["data"] == {"echo": {"title": "T"}}
        assert calls == [("linear__create_issue", {"title": "T"})]
        assert audits[0]["tool_name"] == "linear__create_issue"
        assert audits[0]["result_status"] == "success"
    finally:
        lh._sessions.pop(token, None)

    # Expired token → 404 (turn ended)
    r = mcp_client.post(f"/local-agent-mcp/{token}", json={
        "jsonrpc": "2.0", "id": 4, "method": "tools/list",
    })
    assert r.status_code == 404


# ── Command assembly ─────────────────────────────────────────────────────


@pytest.fixture
def fake_binaries_all(monkeypatch):
    monkeypatch.setattr(
        "nodes.agent.local_harness.shutil.which",
        lambda name: f"/fake/bin/{name}"
        if name in ("claude", "codex", "opencode", "hermes", "openclaw") else None,
    )


@pytest.fixture
def fake_binaries(monkeypatch):
    monkeypatch.setattr(
        "nodes.agent.local_harness.shutil.which",
        lambda name: f"/fake/bin/{name}" if name in ("claude", "codex", "opencode") else None,
    )


def test_claude_command_assembly(fake_binaries, tmp_path):
    cmd, kind = _build_command(
        "claude_code",
        _config(system_prompt="be terse", claude_code_model="opus"),
        tmp_path, "http://127.0.0.1:8000/local-agent-mcp/tok",
    )
    assert kind == "claude_stream_json"
    assert cmd[0] == "/fake/bin/claude"
    assert "--output-format" in cmd and "stream-json" in cmd
    assert "--append-system-prompt" in cmd
    assert cmd[cmd.index("--model") + 1] == "opus"
    mcp_file = tmp_path / ".noclick-mcp.json"
    assert cmd[cmd.index("--mcp-config") + 1] == str(mcp_file)
    assert json.loads(mcp_file.read_text())["mcpServers"]["noclick"]["url"].endswith("/tok")
    assert "--allowedTools" in cmd
    assert "--continue" not in cmd  # fresh workspace

    (tmp_path / ".noclick-turns").touch()
    cmd2, _ = _build_command("claude_code", _config(), tmp_path, None)
    assert "--continue" in cmd2
    assert "--mcp-config" not in cmd2  # no tools wired


def test_codex_command_assembly(fake_binaries, tmp_path):
    cmd, kind = _build_command(
        "codex", _config(system_prompt="be terse", codex_model="gpt-5-codex"),
        tmp_path, "http://127.0.0.1:8000/local-agent-mcp/tok",
    )
    assert kind == "codex_jsonl"
    assert cmd[:2] == ["/fake/bin/codex", "exec"]
    assert "--json" in cmd and "--skip-git-repo-check" in cmd
    assert cmd[cmd.index("-m") + 1] == "gpt-5-codex"
    assert any(a.startswith('mcp_servers.noclick.url="http') for a in cmd)
    # Headless exec has no approval answerer: without this, codex auto-cancels
    # every MCP tool call ("user cancelled MCP tool call").
    assert 'mcp_servers.noclick.default_tools_approval_mode="approve"' in cmd
    # System prompt inlined into the prompt (codex has no system flag here)
    assert cmd[-1].startswith("System instructions:\nbe terse")


def test_opencode_command_assembly(fake_binaries, tmp_path):
    cmd, kind = _build_command(
        "opencode", _config(opencode_model="anthropic/claude-sonnet"),
        tmp_path, "http://127.0.0.1:8000/local-agent-mcp/tok",
    )
    assert kind == "plain_text"
    assert cmd[:2] == ["/fake/bin/opencode", "run"]
    oc = json.loads((tmp_path / "opencode.json").read_text())
    assert oc["mcp"]["noclick"]["type"] == "remote"
    assert cmd[cmd.index("-m") + 1] == "anthropic/claude-sonnet"


def test_missing_binary_fails_loud(monkeypatch, tmp_path):
    monkeypatch.setattr("nodes.agent.local_harness.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError, match="not installed"):
        _build_command("claude_code", _config(), tmp_path, None)


# ── Output parsing ───────────────────────────────────────────────────────


def test_parse_claude_stream_json():
    stdout = "\n".join([
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}),
        json.dumps({"type": "result", "subtype": "success", "result": "final answer", "is_error": False}),
    ])
    response, is_error = _parse_output("claude_stream_json", stdout, "", 0)
    assert (response, is_error) == ("final answer", False)

    response, is_error = _parse_output(
        "claude_stream_json",
        json.dumps({"type": "result", "subtype": "error_during_execution", "result": "boom", "is_error": True}),
        "", 0,
    )
    assert (response, is_error) == ("boom", True)


def test_parse_codex_jsonl():
    stdout = "\n".join([
        json.dumps({"type": "item.completed", "item": {"item_type": "reasoning", "text": "thinking"}}),
        json.dumps({"type": "item.completed", "item": {"item_type": "agent_message", "text": "codex says hi"}}),
    ])
    response, is_error = _parse_output("codex_jsonl", stdout, "", 0)
    assert (response, is_error) == ("codex says hi", False)


def test_parse_codex_jsonl_current_schema():
    """codex spells the item's kind `type`, not `item_type`, in current releases.

    Only the older spelling was covered, so when the binary changed the parser
    silently stopped matching and handed the raw JSONL stream back as the
    agent's answer instead of failing — the run looked successful.
    """
    stdout = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "019fe0cd"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed",
                    "item": {"id": "item_0", "type": "agent_message", "text": "Hi."}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 13244}}),
    ])
    response, is_error = _parse_output("codex_jsonl", stdout, "", 0)
    assert (response, is_error) == ("Hi.", False)
    assert "thread.started" not in response


def test_parse_codex_jsonl_surfaces_the_real_error():
    """A failed turn must report the provider's sentence, not the event stream.

    codex wraps the provider's JSON error body in a string inside its own error
    event, so the actionable line ("requires a newer version of Codex") sits two
    levels down. Without unwrapping, the whole stream landed in the node's error
    field and read like a crash instead of an instruction.
    """
    inner = json.dumps({
        "type": "error", "status": 400,
        "error": {"type": "invalid_request_error",
                  "message": "The 'gpt-5.6-luna' model requires a newer version of Codex."},
    })
    stdout = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "019fe10a"}),
        # soft warning first — the fatal error must win
        json.dumps({"type": "item.completed", "item": {
            "id": "item_0", "type": "error",
            "message": "Model metadata for `gpt-5.6-luna` not found."}}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "error", "message": inner}),
        json.dumps({"type": "turn.failed", "error": {"message": inner}}),
    ])
    response, is_error = _parse_output("codex_jsonl", stdout, "", 0)
    assert is_error is True, "a failed turn is a failure even when the CLI exits 0"
    assert response == "The 'gpt-5.6-luna' model requires a newer version of Codex."
    assert "thread.started" not in response


def test_parse_plain_text():
    assert _parse_output("plain_text", "  the answer \n", "", 0) == ("the answer", False)
    assert _parse_output("plain_text", "", "err", 1) == ("err", True)


# ── Full turn through a fake binary ──────────────────────────────────────


@pytest.mark.asyncio
async def test_run_local_harness_turn_end_to_end(monkeypatch, tmp_path):
    # Fake `claude` that emits a stream-json result and records its argv/cwd.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        'echo "$@" > "$PWD/.argv"\n'
        """printf '{"type":"result","subtype":"success","result":"local turn done","is_error":false}\\n'\n"""
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("HOME", str(tmp_path))  # workspace under tmp HOME

    persisted = {}

    async def fake_persist(output, **kw):
        persisted.update({"output": output, **kw})

    node = SimpleNamespace(
        workflow_id="wf-local", node_id="agent-1", conversation_id=None,
        chat_routing_id=lambda: "conv-123",
        _persist_llm_assistant_turn=fake_persist,
        _user_env=None,
    )
    output = await run_local_harness_turn(
        node, _config(message="hello", conversation_key="ck-1"),
        {}, "user-1", {}, [], model_type="claude_code",
    )

    assert output["status"] == "completed"
    assert output["response"] == "local turn done"
    assert output["type"] == "agent"
    assert persisted["conversation_id"] == "conv-123"
    assert persisted["raw_text"] == "local turn done"
    assert persisted["agent_errored"] is False

    # Workspace = a listable volume under HOME with the --continue marker.
    from utils.volume_backend import workspace_volume_name

    workspace = (
        tmp_path / ".noclick" / "volumes"
        / workspace_volume_name("wf-local", "agent-1", "ck-1")
    )
    assert workspace.is_dir()
    assert (workspace / ".noclick-turns").exists()
    argv = (workspace / ".argv").read_text()
    assert "-p hello" in argv and "--output-format stream-json" in argv


@pytest.mark.asyncio
async def test_run_local_harness_turn_failure_shape(monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text("#!/bin/sh\necho 'catastrophe' >&2\nexit 3\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("HOME", str(tmp_path))

    async def fake_persist(output, **kw):
        pass

    node = SimpleNamespace(
        workflow_id="wf", node_id="a", conversation_id=None,
        chat_routing_id=lambda: "conv",
        _persist_llm_assistant_turn=fake_persist, _user_env=None,
    )
    output = await run_local_harness_turn(
        node, _config(message="x"), {}, "u", {}, [], model_type="claude_code",
    )
    assert output["status"] == "failed"
    assert "catastrophe" in output["error"]


@pytest.mark.asyncio
async def test_filesystem_volume_mounts_into_workspace(monkeypatch, tmp_path):
    """A wired FilesystemNode's volume dir symlinks into the conversation
    workdir, the model gets the environment note, and the Files-panel volume
    sees files written through the link."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        'echo "$@" > "$PWD/.argv"\n'
        'echo persisted > "$PWD/workspace/from-agent.txt"\n'
        """printf '{"type":"result","subtype":"success","result":"ok","is_error":false}\\n'\n"""
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("HOME", str(tmp_path))

    async def fake_persist(output, **kw):
        pass

    node = SimpleNamespace(
        workflow_id="wf-fs", node_id="agent-1", conversation_id=None,
        chat_routing_id=lambda: "conv",
        _persist_llm_assistant_turn=fake_persist, _user_env=None,
    )
    fs_configs = [{"node_id": "fsnode", "volume_mode": "common", "mount_path": "/workspace"}]
    output = await run_local_harness_turn(
        node, _config(message="save it", conversation_key="ck-9"),
        {}, "u", {}, fs_configs, model_type="claude_code",
    )
    assert output["status"] == "completed"

    from nodes.filesystem_node import get_volume_name
    from utils.volume_backend import LocalVolumeBackend

    volume_name = get_volume_name("wf-fs", "fsnode", "common", "ck-9")
    volume_dir = tmp_path / ".noclick" / "volumes" / volume_name
    assert (volume_dir / "from-agent.txt").read_text().strip() == "persisted"
    listing = await LocalVolumeBackend().list_files(volume_name)
    assert [f["path"] for f in listing["files"]] == ["from-agent.txt"]

    # The model was told about the mount.
    workspace_dirs = list((tmp_path / ".noclick" / "volumes").iterdir())
    ws = [d for d in workspace_dirs if d.name != volume_name][0]
    assert "persistent shared storage" in (ws / ".argv").read_text()


def test_tools_call_streams_step_frames(mcp_client, monkeypatch):
    """The MCP endpoint emits the same id-keyed in_progress→completed frames
    as other agent paths, via the shared wss.sender builders."""
    async def fake_execute_tool(node, tool_name, arguments, tool_configs):
        return {"success": True}

    emitted = []

    async def fake_broadcast(user_id, event):
        emitted.append((user_id, event))
        return {"success": True}

    pending = []

    def fake_spawn(coro, name=None):
        pending.append(coro)

    monkeypatch.setattr("nodes.agent.tool_execution.execute_tool", fake_execute_tool)
    monkeypatch.setattr("utils.tool_call_log.record_tool_call", lambda **kw: None)
    monkeypatch.setattr("utils.event_relay.broadcast_to_user_safe", fake_broadcast)
    monkeypatch.setattr("utils.async_helpers.spawn", fake_spawn)

    token = _register_session(_ToolSession(
        node=SimpleNamespace(workflow_id="wf1"),
        tool_configs={"t__op": {"tool_type": "node_op", "_description": "d", "_parameters": {}}},
        user_id="u9", conversation_id="conv-9",
    ))
    try:
        r = mcp_client.post(f"/local-agent-mcp/{token}", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "t__op", "arguments": {"a": 1}},
        })
        assert r.status_code == 200
    finally:
        lh._sessions.pop(token, None)

    async def _drain():
        for coro in pending:
            await coro

    asyncio.run(_drain())
    assert [e[1].agentic_steps[0].status for e in emitted] == ["in_progress", "completed"]
    steps = [e[1].agentic_steps[0] for e in emitted]
    assert steps[0].id == steps[1].id  # same row updates in place
    assert steps[0].text.startswith("Calling t__op(")
    assert all(e[0] == "u9" and e[1].conversation_id == "conv-9" for e in emitted)


@pytest.mark.asyncio
async def test_turn_sets_and_clears_agent_presence(monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text("#!/bin/sh\nprintf '{\"type\":\"result\",\"result\":\"ok\",\"is_error\":false}\\n'\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NOCLICK_LOCAL", "1")

    import utils.local_relay as local_relay_module
    from utils.local_relay import LocalRelayHub

    hub = LocalRelayHub()
    local_relay_module._hub = hub
    transitions = []
    orig_set, orig_clear = hub.set_agent_presence, hub.clear_agent_presence

    async def spy_set(*a, **kw):
        transitions.append(("set", kw.get("busy", a[-1] if a else None)))
        return await orig_set(*a, **kw)

    async def spy_clear(*a, **kw):
        transitions.append(("clear", None))
        return await orig_clear(*a, **kw)

    hub.set_agent_presence, hub.clear_agent_presence = spy_set, spy_clear

    async def fake_persist(output, **kw):
        pass

    node = SimpleNamespace(
        workflow_id="wf-p", node_id="a1", conversation_id=None,
        chat_routing_id=lambda: "conv", sio=None, sid=None, user_id="u1",
        _persist_llm_assistant_turn=fake_persist, _user_env=None,
    )
    try:
        out = await run_local_harness_turn(
            node, _config(message="x", conversation_key="ckp"),
            {}, "u1", {}, [], model_type="claude_code",
        )
    finally:
        local_relay_module._hub = None
    assert out["status"] == "completed"
    assert transitions == [("set", True), ("clear", None)]
    assert hub._agent_presence == {}  # cleared after the turn


# ── hermes + openclaw adapters ───────────────────────────────────────────


def test_hermes_command_assembly(fake_binaries_all, tmp_path):
    cmd, kind = _build_command(
        "hermes_agent", _config(system_prompt="be terse", hermes_agent_model="anthropic/claude"),
        tmp_path, "http://127.0.0.1:8000/local-agent-mcp/tok",
    )
    assert kind == "plain_text"
    assert cmd[:2] == ["/fake/bin/hermes", "-z"]
    assert cmd[2].startswith("System instructions:\nbe terse")
    # hermes takes the provider as a flag and the model without its prefix.
    assert cmd[cmd.index("-m") + 1] == "claude"
    assert cmd[cmd.index("--provider") + 1] == "anthropic"
    # MCP config written where HERMES_HOME points, with the discovery bound.
    config = (tmp_path / ".hermes" / "config.yaml").read_text()
    assert "mcp_servers:" in config and "/local-agent-mcp/tok" in config
    assert "mcp_discovery_timeout: 20" in config


def test_openclaw_command_assembly(fake_binaries_all, tmp_path):
    cmd, kind = _build_command(
        "openclaw", _config(openclaw_model="anthropic/claude-sonnet"),
        tmp_path, "http://127.0.0.1:8000/local-agent-mcp/tok",
    )
    assert kind == "openclaw_json"
    assert cmd[:4] == ["/fake/bin/openclaw", "agent", "--local", "--json"]
    assert "--message" in cmd and "--session-id" in cmd
    assert cmd[cmd.index("--model") + 1] == "anthropic/claude-sonnet"
    config = json.loads((tmp_path / ".openclaw" / "config.json").read_text())
    assert config["mcp"]["servers"]["noclick"]["url"].endswith("/tok")
    assert config["agents"]["defaults"]["sandbox"]["mode"] == "off"
    assert config["agents"]["defaults"]["workspace"] == str(tmp_path)


def test_openclaw_json_parsing():
    # The real shape (verified against openclaw 2026.6.10 --json output).
    real = json.dumps({
        "payloads": [{"text": "OPENCLAW_LOCAL_OK", "mediaUrl": None}],
        "meta": {"durationMs": 3831, "agentMeta": {"sessionId": "noclick-abc"}},
    })
    assert _parse_output("openclaw_json", real, "", 0) == ("OPENCLAW_LOCAL_OK", False)
    multi = json.dumps({"payloads": [{"text": "one"}, {"text": "two"}]})
    assert _parse_output("openclaw_json", multi, "", 0) == ("one\n\ntwo", False)

    payload = json.dumps({"ok": True, "reply": "openclaw says hi"})
    assert _parse_output("openclaw_json", payload, "", 0) == ("openclaw says hi", False)
    # JSONL variant: last object wins
    lines = "\n".join([json.dumps({"event": "start"}), json.dumps({"text": "final answer"})])
    assert _parse_output("openclaw_json", lines, "", 0) == ("final answer", False)
    # Nested content shape
    nested = json.dumps({"message": {"text": "nested reply"}})
    assert _parse_output("openclaw_json", nested, "", 0) == ("nested reply", False)
    # Unparseable → raw passthrough, error propagates
    assert _parse_output("openclaw_json", "not json", "", 1) == ("not json", True)


@pytest.mark.asyncio
async def test_hermes_toolless_turn_is_retried_once(monkeypatch, tmp_path):
    """Upstream hermes' oneshot races MCP discovery; the local runner re-runs
    a toolless turn instead of shipping the hosted build's patched binary."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "hermes"
    # Counts runs; only the SECOND run fetches the tool list (simulating the
    # race resolving once the MCP connection is warm).
    fake.write_text(
        "#!/bin/sh\n"
        'n=$(cat "$PWD/.runs" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$PWD/.runs"\n'
        'if [ "$n" -ge 2 ]; then\n'
        '  curl -s -X POST "$NC_MCP_URL" -H "content-type: application/json" '
        '-d \'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\' > /dev/null 2>&1\n'
        "fi\n"
        'echo "hermes reply $n"\n'
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("HOME", str(tmp_path))

    async def fake_persist(output, **kw):
        pass

    node = SimpleNamespace(
        workflow_id="wf-h", node_id="a1", conversation_id=None,
        chat_routing_id=lambda: "conv", sio=None, sid=None, user_id="u1",
        _persist_llm_assistant_turn=fake_persist, _user_env=None,
    )

    # Serve the tool endpoint so the fake binary's tools/list lands for real.
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8123, log_level="error"))
    serve_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    monkeypatch.setenv("PORT", "8123")

    try:
        # The fake binary needs the URL; the runner writes it into hermes config,
        # so hand it over through the environment too.
        monkeypatch.setattr(
            lh, "_mcp_url",
            lambda token: f"http://127.0.0.1:8123/local-agent-mcp/{token}",
        )
        real_build = lh._build_command

        def build_with_env(model_type, config, workdir, mcp_url, extra_note=""):
            cmd, kind = real_build(model_type, config, workdir, mcp_url, extra_note)
            os.environ["NC_MCP_URL"] = mcp_url or ""
            return cmd, kind

        monkeypatch.setattr(lh, "_build_command", build_with_env)

        output = await run_local_harness_turn(
            node, _config(message="hi", conversation_key="ck-h"),
            {}, "u1",
            {"t__op": {"tool_type": "node_op", "_description": "d", "_parameters": {}}},
            [], model_type="hermes_agent",
        )
    finally:
        server.should_exit = True
        await serve_task

    # Second run's output wins — the toolless first turn was discarded.
    assert output["response"] == "hermes reply 2"


def test_the_tool_endpoint_targets_the_backends_own_port(monkeypatch):
    """PORT is the public port on every PaaS (nginx in the single-origin image,
    which has no /local-agent-mcp route): pointed there, the CLI handshakes
    with an HTML page and runs toolless. The backend's own bind wins."""
    from nodes.agent.local_harness import _mcp_url

    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("NOCLICK_BACKEND_PORT", "8000")
    assert _mcp_url("tok") == "http://127.0.0.1:8000/local-agent-mcp/tok"
    monkeypatch.delenv("NOCLICK_BACKEND_PORT")
    assert _mcp_url("tok") == "http://127.0.0.1:8080/local-agent-mcp/tok"
    monkeypatch.delenv("PORT")
    assert _mcp_url("tok") == "http://127.0.0.1:8000/local-agent-mcp/tok"


def test_codex_401_on_a_chatgpt_sign_in_explains_the_plan():
    import base64
    from nodes.agent.local_harness import explain_codex_failure

    def id_token(plan):
        b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
        claims = {"https://api.openai.com/auth": {"chatgpt_plan_type": plan}}
        return b64({"alg": "RS256"}) + "." + b64(claims) + ".sig"

    bare = "unexpected status 401 Unauthorized: Missing bearer or basic authentication in header, url: https://api.openai.com/v1/responses"
    # A definitively Free id token names the plan.
    free = explain_codex_failure(bare, chatgpt_auth=True, id_token=id_token("free"))
    assert "Free plan" in free and "OpenAI API key" in free
    # No id token: the plan is unknowable — an incomplete sign-in must never be
    # accused of being Free (a Pro user got exactly that, 2026-08-31).
    unknown = explain_codex_failure(bare, chatgpt_auth=True)
    assert "identity token" in unknown and "Free plan" not in unknown
    # A paid plan that still fell back gets reconnect guidance, not an accusation.
    paid = explain_codex_failure(bare, chatgpt_auth=True, id_token=id_token("pro"))
    assert "pro" in paid and "Free plan" not in paid
    # An API-key run that 401s is a different problem and keeps codex's words.
    assert explain_codex_failure(bare, chatgpt_auth=False) == bare
    assert explain_codex_failure("model not found", chatgpt_auth=True) == "model not found"


def test_hermes_takes_the_provider_as_a_flag_and_the_model_without_its_prefix():
    from nodes.agent.local_harness import hermes_provider_and_model

    # The agent's default id: hermes rejected it whole ("not a valid model ID").
    assert hermes_provider_and_model("openrouter/openai/gpt-5.6-luna") == ("openrouter", "openai/gpt-5.6-luna")
    assert hermes_provider_and_model("gemini/gemini-3.5-flash") == ("google", "gemini-3.5-flash")
    assert hermes_provider_and_model("anthropic/claude-sonnet-4") == ("anthropic", "claude-sonnet-4")
    # Unknown prefixes and bare ids are hermes's to auto-detect.
    assert hermes_provider_and_model("nousresearch/hermes-3-70b") == (None, "nousresearch/hermes-3-70b")
    assert hermes_provider_and_model("") == (None, "")


def test_openclaw_mcp_server_uses_a_transport_openclaw_accepts(tmp_path, monkeypatch):
    import json
    from nodes.agent import local_harness

    monkeypatch.setattr(local_harness, "_require_binary", lambda name, hint: f"/fake/bin/{name}")
    local_harness._build_command("openclaw", _config(openclaw_model="openrouter/openai/gpt-5-mini"), tmp_path, "http://127.0.0.1:8000/local-agent-mcp/tok")
    config = json.loads((tmp_path / ".openclaw" / "config.json").read_text())
    # "http" failed openclaw's config validation before any turn ran.
    assert config["mcp"]["servers"]["noclick"] == {"transport": "streamable-http", "url": "http://127.0.0.1:8000/local-agent-mcp/tok"}


def test_the_cli_never_sees_the_credential_transport_vars(tmp_path):
    """codex (0.147) treats CODEX_ACCESS_TOKEN in its environment as an auth
    override and abandons auth.json for a keyless API mode — a valid pro
    sign-in died with bearer-less 401s (2026-08-31, bisected var by var
    against the live binary). The tokens reach the CLI through its config
    file only; the env vars are backend-internal transport."""
    from nodes.agent.local_harness import _apply_subscription_login
    import json as _json

    env = {"PATH": "/usr/bin", "CODEX_ACCESS_TOKEN": "acc", "CODEX_ID_TOKEN": "idt",
           "CODEX_REFRESH_TOKEN": "ref", "CODEX_EXPIRES_AT": "2027-01-01T00:00:00Z"}
    _apply_subscription_login("codex", tmp_path, env)
    written = _json.loads((tmp_path / ".codex" / "auth.json").read_text())
    assert written["tokens"]["access_token"] == "acc"
    assert written["tokens"]["id_token"] == "idt"
    assert env["CODEX_HOME"] == str(tmp_path / ".codex")
    assert not any(k.startswith("CODEX_") and k != "CODEX_HOME" for k in env)

    env = {"PATH": "/usr/bin", "CLAUDE_CODE_ACCESS_TOKEN": "cacc",
           "CLAUDE_CODE_REFRESH_TOKEN": "cref", "CLAUDE_CODE_EXPIRES_AT": "2027-01-01T00:00:00Z"}
    _apply_subscription_login("claude_code", tmp_path, env)
    creds = _json.loads((tmp_path / ".claude" / ".credentials.json").read_text())
    assert creds["claudeAiOauth"]["accessToken"] == "cacc"
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / ".claude")
    assert not any(k.startswith("CLAUDE_CODE_") for k in env)


def test_mcp_notifications_get_an_empty_202(mcp_client, monkeypatch):
    """JSON-RPC notifications must get 202 with NO body (Streamable HTTP).
    Answering 200 {} broke codex's rmcp client mid-handshake — it looped on
    initialize and never issued tools/list, so every codex turn ran toolless
    while the server logged nothing but 200s (2026-08-31)."""
    from nodes.agent.local_harness import _ToolSession, _register_session, _sessions

    token = _register_session(_ToolSession(
        node=object(), tool_configs={}, user_id="u", conversation_id="c",
    ))
    try:
        r = mcp_client.post(f"/local-agent-mcp/{token}", json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        assert r.status_code == 202
        assert r.content == b""
        # Requests (with an id) still answer JSON-RPC results.
        r = mcp_client.post(f"/local-agent-mcp/{token}", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        })
        assert r.status_code == 200
        assert r.json()["result"] == {"tools": []}
    finally:
        _sessions.pop(token, None)


def test_the_prompt_grounds_the_wired_tools():
    """The MCP advertisement alone is not always believed — a ChatGPT-backend
    model matched "apollo" against its own connector catalogue and answered
    "not installed" while the tools sat in its own tool list."""
    from nodes.agent.local_harness import _tools_note

    note = _tools_note({"apollo__search_people_in_apollo": {}, "upload_file": {}})
    assert "apollo__search_people_in_apollo" in note and "upload_file" in note
    assert "noclick" in note
    assert _tools_note({}) == ""
