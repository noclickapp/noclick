"""An agent's sandbox: ``agent.sandbox()`` reads what it is and costs (``get``), its files a folder
at a time (``files``, ``files_page``, ``read``), writes one into it (``write``, ``set_env``) and runs a
command beside the agent's work (``exec``); ``Agent.coding()`` reads every coding agent and what each is
doing."""

import pytest

import noclick as nc
from platform_helpers import agent_row, body

AGENT = agent_row(id="ag_1", name="coder", harness="claude_code", model="claude-sonnet-4-5")
SANDBOX = {"object": "agent_sandbox", "agent_id": "ag_1", "conversation": "user:42/main", "harness": "claude_code",
           "place": "sandbox", "status": "running", "started_at": "2026-11-09T10:00:00Z", "cpu": 1.0,
           "memory_mb": 4096, "region": None, "usd_per_hour": 0.162, "spent_usd_today": 0.012, "machine_id": None,
           "project_id": None, "workspace": "/workspace"}
ENTRY = {"object": "sandbox_entry", "path": "/workspace/src", "type": "directory", "size": None, "updated_at": None}
PATH = "/v1/agents/ag_1/conversations/user%3A42%2Fmain/sandbox"


def test_what_a_conversations_sandbox_is_and_costs(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    read = api.get(PATH).respond(json=SANDBOX)
    machine = nc.Agent.from_id("ag_1").sandbox("user:42/main")
    assert read.call_count == 0 and repr(machine) == "AgentSandbox(conversation='user:42/main')"
    now = machine.get()
    assert isinstance(now, nc.ConversationSandbox)
    assert (now.place, now.status, now.cpu, now.memory_mb, now.usd_per_hour, now.spent_usd_today, now.workspace) == (
        "sandbox", "running", 1.0, 4096, 0.162, 0.012, "/workspace")
    assert now.started_at.isoformat() == "2026-11-09T10:00:00+00:00"


def test_without_a_conversation_it_is_read_through_the_agents_session(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    sessions = api.get("/v1/agents/ag_1/conversations").mock(side_effect=[
        nc_response({"object": "list", "data": [{"object": "conversation", "conversation": "c9", "active": True}],
                     "next_cursor": None}),
        nc_response({"object": "list", "data": [{"object": "conversation", "conversation": "c1", "active": False}],
                     "next_cursor": None}),
    ])
    read = api.get("/v1/agents/ag_1/conversations/c9/sandbox").respond(json={**SANDBOX, "conversation": "c9"})
    assert nc.Agent.from_id("ag_1").sandbox().get().status == "running" and read.call_count == 1
    with pytest.raises(nc.NotFound):
        nc.Agent.from_id("ag_1").sandbox().get()
    assert sessions.call_count == 2


def test_its_files_a_folder_at_a_time_and_one_files_bytes(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    files = api.get(f"{PATH}/files")
    files.side_effect = [
        nc_response({"object": "list", "data": [ENTRY], "next_cursor": "/workspace/src", "source": "sandbox"}),
        nc_response({"object": "list", "data": [{**ENTRY, "path": "/workspace/src/a.py", "type": "file", "size": 3}],
                     "next_cursor": None, "source": "sandbox"}),
    ]
    machine = nc.Agent.from_id("ag_1").sandbox("user:42/main")
    entries = machine.files("/workspace", recursive=True)
    assert [(e.path, e.type, e.size) for e in entries] == [("/workspace/src", "directory", None),
                                                           ("/workspace/src/a.py", "file", 3)]
    first, second = (call.request.url.params for call in files.calls)
    assert (first["view"], first["recursive"], second["cursor"]) == ("list", "true", "/workspace/src")

    files.side_effect = None
    files.respond(json={"object": "list", "data": [ENTRY], "next_cursor": "/workspace/src", "source": "workspace"})
    page = machine.files_page(limit=1)
    assert isinstance(page, nc.SandboxFilesPage)
    assert (page.source, page.next_cursor, page.data[0].path) == ("workspace", "/workspace/src", "/workspace/src")

    files.respond(json={"object": "list", "data": [ENTRY], "next_cursor": None, "source": "machine"})
    assert machine.files_page().source == "machine"

    files.respond(content=b"TOKEN=[redacted]")
    assert machine.read("/workspace/.env") == b"TOKEN=[redacted]"
    assert files.calls.last.request.url.params["path"] == "/workspace/.env"


def test_a_file_written_into_its_running_sandbox_raw_holding_secrets(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    put = api.put(f"{PATH}/files").respond(json={
        "object": "sandbox_entry", "path": "/workspace/.npmrc", "type": "file", "size": 24,
        "updated_at": "2026-11-27T10:00:00Z"})
    machine = nc.Agent.from_id("ag_1").sandbox("user:42/main")
    written = machine.write("/workspace/.npmrc", "//registry/:_authToken=t\n", secret=True)
    assert isinstance(written, nc.VolumeEntry)
    assert (written.path, written.type, written.size) == ("/workspace/.npmrc", "file", 24)
    sent = put.calls.last.request
    assert dict(sent.url.params) == {"path": "/workspace/.npmrc", "secret": "true"}
    assert sent.content == b"//registry/:_authToken=t\n"
    assert sent.headers["content-type"] == "application/octet-stream"

    machine.write("/root/bin/deploy", b"#!", mode="0755")
    assert dict(put.calls.last.request.url.params) == {"path": "/root/bin/deploy", "mode": "0755"}
    assert put.calls.last.request.content == b"#!"


def test_a_dotenv_files_keys_set_and_unset_in_place_the_answer_names_its_keys(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    patch = api.patch(f"{PATH}/files").respond(json={
        "object": "sandbox_env", "keys": ["DATABASE_URL", "STRIPE_KEY"],
        "entry": {"object": "sandbox_entry", "path": "/workspace/app/.env", "type": "file", "size": 61,
                  "updated_at": None}})
    env = nc.Agent.from_id("ag_1").sandbox("user:42/main").set_env(
        "/workspace/app/.env", set={"STRIPE_KEY": "sk_test_1"}, unset=["OLD_KEY"])
    assert patch.calls.last.request.url.params["path"] == "/workspace/app/.env"
    assert body(patch.calls.last.request) == {"set": {"STRIPE_KEY": "sk_test_1"}, "unset": ["OLD_KEY"]}
    assert isinstance(env, nc.SandboxEnv)
    assert (env.entry.path, env.entry.size, env.keys) == ("/workspace/app/.env", 61, ["DATABASE_URL", "STRIPE_KEY"])
    assert "sk_test_1" not in repr(env)


def test_a_command_beside_the_agents_work(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    ran = api.post(f"{PATH}/exec").respond(json={
        "object": "sandbox_exec", "agent_id": "ag_1", "conversation": "user:42/main", "exit_code": 0,
        "stdout": "M a.py\n", "stderr": "", "timed_out": False, "stdout_truncated": False, "stderr_truncated": False})
    result = nc.Agent.from_id("ag_1").sandbox("user:42/main").exec("git status --short", timeout_s=30)
    assert body(ran.calls.last.request) == {"command": "git status --short", "timeout_s": 30}
    assert (result.ok, result.stdout) == (True, "M a.py\n")


def test_every_coding_agent_and_what_its_doing(api, client):
    read = api.get("/v1/agents/coding").respond(json={
        "object": "list", "read_at": "2026-11-09T10:05:00Z", "unread": ["sandboxes"],
        "data": [{
            "object": "coding_agent", "agent_id": "ag_1", "name": "coder", "user_id": None,
            "app": {"project_id": "prj_1", "name": "bakery", "title": "Morrow Bakehouse", "coder": True},
            "harness": "codex", "model": "gpt-6-luna",
            "credential": {"kind": "plan", "connection": "chatgpt", "credential_type": "agent_codex_oauth",
                           "connected": True},
            "place": "sandbox", "state": "working", "paused": None, "pauses": [],
            "job": {"operation_id": "op_1", "conversation": "code", "status": "running", "step": "working",
                    "since": "2026-11-09T10:00:00Z", "title": "Fix the menu", "text": "Fix the menu page"},
            "runs": [{"conversation": "code", "place": "sandbox", "since": "2026-11-09T09:59:00Z", "busy": True,
                      "cpu": 1.0, "memory_mb": 4096}],
            "spent_usd_this_month": 1.25,
            "model_usage_this_month": {"input_tokens": 10, "output_tokens": 5, "cached_tokens": 2, "usd": 0.4},
        }],
        "counts": [{"harness": "codex", "model": "gpt-6-luna", "state": "working", "place": "sandbox", "count": 1}],
        "by_state": {"working": 1, "waiting": 0, "warm": 0, "paused": 0, "stopped": 0}, "paused_by_reason": {},
    })
    coding = nc.Agent.coding()
    assert isinstance(coding, nc.CodingAgents)
    [agent] = coding.agents
    assert (agent.name, agent.state, agent.app.title, agent.credential.kind, agent.job.title, agent.job.lost) == (
        "coder", "working", "Morrow Bakehouse", "plan", "Fix the menu", False)
    assert (agent.runs[0].busy, agent.runs[0].cpu, agent.runs[0].memory_mb, agent.runs[0].daemon) == (
        True, 1.0, 4096, None)
    assert (agent.spent_usd_this_month, agent.model_usage_this_month.usd) == (1.25, 0.4)
    assert (coding.counts[0].count, coding.by_state["working"], coding.unread) == (1, 1, ["sandboxes"])
    assert "user_id" not in read.calls.last.request.url.params
    nc.Agent.coding(user_filter=nc.ALL_USERS)
    assert read.calls.last.request.url.params["user_id"] == "all"


def nc_response(payload):
    import httpx

    return httpx.Response(200, json=payload)


def test_a_shell_is_a_token_for_the_browser(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    opened = api.post(f"{PATH}/shell").respond(json={
        "object": "sandbox_shell", "agent_id": "ag_1", "conversation": "user:42/main",
        "url": "wss://api.test/v1/terminals/attach", "token": "tok_1", "token_expires_at": "2026-11-09T10:02:00Z",
        "idle_limit_s": 900})
    shell = nc.Agent.from_id("ag_1").sandbox("user:42/main").shell()
    assert opened.call_count == 1 and isinstance(shell, nc.SandboxShell)
    assert (shell.url, shell.token, shell.idle_limit_s) == ("wss://api.test/v1/terminals/attach", "tok_1", 900)
    assert shell.token_expires_at.isoformat() == "2026-11-09T10:02:00+00:00"
    assert "tok_1" not in repr(shell)  # a token opens the shell: never in a log line
