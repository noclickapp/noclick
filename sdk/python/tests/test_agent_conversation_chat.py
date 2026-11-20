"""A conversation as a chat drives it (``agent.conversation(name)``): its settings, a fork, a revert, its context and
usage, a command NoClick has a control for; starting and listing conversations; the agent's one session, cleared and
resumed; every agent's state; an agent's effort and speed and what each harness takes."""

import httpx

import noclick as nc
from platform_helpers import agent_row, body, operation

AGENT = agent_row(id="ag_1", name="coder", harness="claude_code", effort="high", speed="standard")
SETTINGS = {
    "object": "conversation_settings", "conversation": "main", "title": "Retries", "archived": False,
    "harness": "claude_code", "model": "opus", "effort": "high", "efforts": ["low", "medium", "high", "xhigh", "max"],
    "default_effort": None, "speed": "fast", "speeds": ["standard", "fast"], "model_connection": "claude",
    "accounts": [{"name": "claude", "integration": "anthropic", "kind": "plan", "connected": True, "usable": True,
                  "why": None}],
    "overridden": ["model", "speed"], "permission_mode": "full-access", "effective_permission_mode": "full-access",
    "permission_modes": ["full-access"], "not_supported": {}, "forked_from": None,
}
CONVERSATION = {
    "object": "agent_conversation", "conversation": "c1a2", "user_id": None, "title": "Retries (fork)",
    "preview": "Fix it", "turns": 2, "cost_usd": 0.1, "last_activity": "2026-11-10T10:05:00Z", "status": "active",
    "last_message": {"role": "assistant", "text": "Done.", "created_at": "2026-11-10T10:05:00Z"},
    "people": [{"type": "account", "id": None, "name": "Grace"}], "archived": False,
    "forked_from": {"conversation": "main", "message": "4", "through": "5"}, "agent_reads": "native",
}


def test_a_conversations_settings_are_read_and_changed(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.get("/v1/agents/ag_1/conversations/main/settings").respond(json=SETTINGS)
    patched = api.patch("/v1/agents/ag_1/conversations/main").respond(json={**SETTINGS, "model": "sonnet"})
    chat = nc.Agent.from_id("ag_1").conversation("main")
    settings = chat.settings()
    assert (settings.model, settings.effort, settings.speed, settings.efforts[-1]) == ("opus", "high", "fast", "max")
    assert settings.overridden == ["model", "speed"] and settings.accounts[0]["kind"] == "plan"
    chat.update(model=None, effort="max", archived=True)
    assert body(patched.calls.last.request) == {"model": None, "effort": "max", "archived": True}


def test_a_conversation_is_started_forked_reverted_and_read(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    started = api.post("/v1/agents/ag_1/conversations").respond(json={**CONVERSATION, "forked_from": None})
    forked = api.post("/v1/agents/ag_1/conversations/main/fork").respond(json=CONVERSATION)
    reverted = api.post("/v1/agents/ag_1/conversations/main/revert").respond(json={
        "object": "conversation_revert", "conversation": "main", "message": "0", "text": "Fix it", "dropped_turns": 1,
        "files": {"restored": ["app.py"], "kept": [], "not_restored": [], "commands_not_undone": 0},
        "files_applied": "next_turn", "agent_reads": "native"})
    api.get("/v1/agents/ag_1/conversations/main/context").respond(json={
        "object": "conversation_context", "model": "opus", "used_tokens": 50000, "window_tokens": 200000,
        "percent": 25.0, "auto_compacts_at": None, "source": "harness", "as_of": "2026-11-10T10:05:00Z"})
    api.get("/v1/agents/ag_1/conversations/main/usage").respond(json={
        "object": "conversation_usage", "cost_usd": 0.42, "model_usage": None, "turns": 3, "pays_with": "plan",
        "plan_limits": [{"label": "5-hour limit", "used_percent": 31, "resets_at": "2026-11-10T14:00:00Z"}]})
    listed = api.get("/v1/agents/ag_1/conversations").respond(json={"object": "list", "data": [CONVERSATION],
                                                                    "next_cursor": None})
    coder = nc.Agent.from_id("ag_1")
    coder.start_conversation(title="Retries")
    assert body(started.calls.last.request) == {"title": "Retries"}
    fork = coder.conversation("main").fork(message="4")
    assert body(forked.calls.last.request) == {"message": "4"}
    assert (fork.forked_from["through"], fork.agent_reads) == ("5", "native")
    undone = coder.conversation("main").revert("0", files=True)
    assert body(reverted.calls.last.request) == {"message": "0", "files": True}
    assert (undone.text, undone.files["restored"], undone.files_applied) == ("Fix it", ["app.py"], "next_turn")
    context = coder.conversation("main").context()
    assert (context.used_tokens, context.percent, context.source) == (50000, 25.0, "harness")
    usage = coder.conversation("main").usage()
    assert (usage.cost_usd, usage.pays_with, usage.plan_limits[0]["label"]) == (0.42, "plan", "5-hour limit")
    [one] = coder.conversations(archived=False)
    assert listed.calls.last.request.url.params["archived"] == "false"
    assert (one.last_message["text"], one.people[0]["name"]) == ("Done.", "Grace")


def test_an_agent_is_one_session_cleared_resumed_and_read(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    cleared = api.post("/v1/agents/ag_1/conversations").respond(
        json={**CONVERSATION, "conversation": "c9", "forked_from": None, "active": True}, status_code=201)
    resumed = api.post("/v1/agents/ag_1/conversations/c1a2/resume").respond(json={**CONVERSATION, "active": True})
    listed = api.get("/v1/agents/ag_1/conversations").mock(side_effect=[
        httpx.Response(200, json={"object": "list", "data": [{**CONVERSATION, "conversation": "c9"}],
                                  "next_cursor": "p2"}),
        httpx.Response(200, json={"object": "list", "data": [{**CONVERSATION, "active": True}], "next_cursor": None}),
    ])
    coder = nc.Agent.from_id("ag_1")
    fresh = coder.clear(title="Billing")
    assert body(cleared.calls.last.request) == {"title": "Billing"}
    assert (fresh.conversation, fresh.active) == ("c9", True)
    back = coder.conversation("c1a2").resume()
    assert resumed.called and back.active
    current = coder.session()
    assert current.conversation == "c1a2" and current.active
    assert listed.calls.last.request.url.params["cursor"] == "p2"


def test_a_command_noclick_has_a_control_for_comes_back_as_its_result(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    sent = api.post("/v1/agents/ag_1/messages").respond(json={
        "object": "command_result", "command": {"name": "effort", "arguments": "high"}, "control": "effort",
        "result": SETTINGS})
    outcome = nc.Agent.from_id("ag_1").conversation("main").run_command("effort", "high")
    assert body(sent.calls.last.request) == {"command": {"name": "effort", "arguments": "high"}, "conversation": "main"}
    assert isinstance(outcome, nc.CommandResult) and outcome.control == "effort"


def test_every_agents_state_and_the_harnesses_traits(api, client):
    states = api.get("/v1/agents/states").respond(json={"object": "list", "read_at": "2026-11-10T10:05:00Z", "data": [{
        "agent_id": "ag_1", "name": "coder", "harness": "claude_code", "state": "needs_you", "conversation": "main",
        "now": {"tool": "Bash", "kind": "command", "line": "bash: pytest -x", "since": None, "running": True},
        "waiting": {"asks": 1, "held_calls": 0, "requests": 2, "total": 3}, "turn_started_at": None,
        "last_active_at": None, "failed": None, "waking": None}]})
    [row] = nc.Agent.states(workspace="ws_1")
    assert states.calls.last.request.url.params["workspace_id"] == "ws_1"
    assert (row.state, row.now["line"], row.waiting["total"]) == ("needs_you", "bash: pytest -x", 3)
    api.get("/v1/harnesses").respond(json={"object": "list", "data": [{
        "object": "harness", "name": "codex", "label": "Codex", "version": "0.162.0", "default_model": "gpt-5-codex",
        "custom_models": True, "model_connection": "required", "integrations": ["openai"], "streaming": "final",
        "shell": "built_in", "notes": [], "efforts": ["minimal", "low", "medium", "high", "xhigh"],
        "default_effort": "medium", "speeds": [], "noclick_key": {"runs": True, "models": ["gpt-6-luna"]}}]})
    [codex] = nc.Agent.harnesses()
    assert (codex.default_effort, codex.noclick_key["runs"]) == ("medium", True)
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    agent = nc.Agent.get("ag_1")
    assert (agent.effort, agent.speed) == ("high", "standard")
    made = api.post("/v1/agents").respond(json=AGENT, status_code=201)
    nc.Agent.create("fixer", instructions="Fix it.", harness="codex", model_connection="noclick", effort="low")
    assert body(made.calls.last.request)["effort"] == "low"



TOOL_SERVERS = {
    "object": "tool_servers", "source": "live", "checked_at": "2026-11-10T10:06:00Z",
    "data": [{"name": "noclick", "status": "connected", "tool_count": 12, "error": None},
             {"name": "linear", "status": "failed", "tool_count": None, "error": "401 from the server"}],
    "reconnect": {"available": True, "scope": "server", "why": None},
}


def test_a_conversations_tool_servers_are_read_live_and_one_is_reconnected(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.get("/v1/agents/ag_1/conversations/main/tool_servers").respond(json=TOOL_SERVERS)
    again = api.post("/v1/agents/ag_1/conversations/main/tool_servers/linear/reconnect").respond(json={
        **TOOL_SERVERS, "data": [TOOL_SERVERS["data"][0], {**TOOL_SERVERS["data"][1], "status": "connecting"}]})
    chat = nc.Agent.from_id("ag_1").conversation("main")
    servers = chat.tool_servers()
    assert servers.source == "live" and servers.reconnect == {"available": True, "scope": "server", "why": None}
    assert [(s.name, s.status, s.tool_count, s.error) for s in servers.servers] == [
        ("noclick", "connected", 12, None), ("linear", "failed", None, "401 from the server")]
    assert servers.servers[0].tools is None
    assert chat.reconnect_tool_server("linear").servers[1].status == "connecting" and again.called


def test_an_agents_mcp_server_takes_headers_which_change_and_read_back_by_name(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    server = {"object": "agent_tool_server", "id": "mcp_docs", "name": "docs", "url": "https://mcp.docs.example.com/mcp",
              "transport": "http", "signed_in": False, "headers": ["X-Api-Key"]}
    added = api.post("/v1/agents/ag_1/tool_servers").respond(json=server, status_code=201)
    changed = api.patch("/v1/agents/ag_1/tool_servers/mcp_docs").respond(json={**server, "headers": []})
    coder = nc.Agent.from_id("ag_1")
    docs = coder.add_tool_server("https://mcp.docs.example.com/mcp", name="docs", headers={"X-Api-Key": "k-1"})
    assert body(added.calls.last.request) == {"url": "https://mcp.docs.example.com/mcp", "transport": "http",
                                              "name": "docs", "headers": {"X-Api-Key": "k-1"}}
    assert (docs.headers, docs.signed_in) == (["X-Api-Key"], False)
    assert coder.update_tool_server(docs, headers={}).headers == []
    assert body(changed.calls.last.request) == {"headers": {}}


def test_a_conversations_tool_servers_name_each_tool_where_the_harness_lists_them(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.get("/v1/agents/ag_1/conversations/main/tool_servers").respond(json={**TOOL_SERVERS, "data": [
        {**TOOL_SERVERS["data"][0], "tool_count": 2, "tools": [
            {"name": "search", "description": "Search the account."}, {"name": "fetch", "description": None}]}]})
    [noclick] = nc.Agent.from_id("ag_1").conversation("main").tool_servers().servers
    assert noclick.tools == [nc.ToolServerTool("search", "Search the account."), nc.ToolServerTool("fetch")]


ADDED_SERVER = {
    "object": "agent_tool_server", "id": "mcp_docs", "agent_id": "ag_1", "name": "docs",
    "url": "https://mcp.docs.example.com/mcp", "host": "mcp.docs.example.com", "transport": "http",
    "signed_in": False, "headers": [], "sign_in": "browser", "status": "signed_out",
    "problem": {"reason": "signed_out", "message": "Its sign-in ended.", "provider_said": "invalid_grant",
                "since": "2026-11-18T09:00:00Z", "next_step": "Sign in to it again."},
    "tools": [{"name": "search_docs", "description": "Search the docs."}],
    "icon": {"integration": "docs"}, "checked_at": "2026-11-18T08:00:00Z",
}


def test_an_agents_mcp_server_says_how_it_stands_and_signs_in_again_by_a_link(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.get("/v1/agents/ag_1/tool_servers").respond(json={"object": "list", "data": [ADDED_SERVER]})
    made = api.post("/v1/agents/ag_1/tool_servers/mcp_docs/connect_link").respond(json={
        "object": "connect_link", "url": "https://noclick.com/c/docs", "expires_at": "2026-11-21T10:00:00Z",
        "operation": operation(op_id="op_s", kind="tool_server.sign_in")}, status_code=201)
    api.get("/v1/operations/op_s/wait").respond(json=operation(
        op_id="op_s", kind="tool_server.sign_in", status="succeeded", result={"tool_server": {
            **ADDED_SERVER, "signed_in": True, "status": "unchecked", "problem": None}}))
    [docs] = nc.Agent.from_id("ag_1").tool_servers()
    assert (docs.host, docs.sign_in, docs.status, docs.icon) == (
        "mcp.docs.example.com", "browser", "signed_out", {"integration": "docs"})
    assert (docs.problem.reason, docs.problem.provider_said, docs.problem.since.day) == ("signed_out", "invalid_grant", 18)
    assert docs.tools == [nc.ToolServerTool("search_docs", "Search the docs.")] and docs.checked_at.hour == 8
    link = docs.connect_link(reason="Sign in to the docs again")
    assert isinstance(link, nc.ConnectLink) and link.url == "https://noclick.com/c/docs" and link.id == "op_s"
    assert body(made.calls.last.request) == {"reason": "Sign in to the docs again"}
    again = link.wait()
    assert isinstance(again, nc.AgentToolServer) and (again.id, again.signed_in, again.status, again.problem) == (
        "mcp_docs", True, "unchecked", None)


def test_an_agents_mcp_servers_read_for_a_conversation_say_which_can_reconnect_in_place(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    read = api.get("/v1/agents/ag_1/tool_servers").respond(json={"object": "list", "data": [{
        **ADDED_SERVER, "status": "failed", "reconnectable": True,
        "problem": {**ADDED_SERVER["problem"], "reason": "failed", "message": "connection refused"}}]})
    [docs] = nc.Agent.from_id("ag_1").tool_servers(conversation="main")
    assert read.calls.last.request.url.params["conversation"] == "main"
    assert (docs.status, docs.reconnectable, docs.problem.message) == ("failed", True, "connection refused")


def test_a_server_read_before_its_state_was_named_reads_as_unchecked(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.get("/v1/agents/ag_1/tool_servers").respond(json={"object": "list", "data": [{
        "object": "agent_tool_server", "id": "mcp_docs", "name": "docs", "url": "https://mcp.docs.example.com/mcp",
        "transport": "http", "signed_in": False, "headers": []}]})
    [docs] = nc.Agent.from_id("ag_1").tool_servers()
    assert (docs.sign_in, docs.status, docs.problem, docs.tools, docs.icon, docs.reconnectable) == (
        "none", "unchecked", None, [], None, False)


def test_an_agents_own_permission_mode_is_what_its_conversations_start_from(api, client):
    api.get("/v1/agents/ag_1").respond(json={**AGENT, "permission_mode": "approval-required"})
    patched = api.patch("/v1/agents/ag_1").respond(json={**AGENT, "permission_mode": "full-access"})
    coder = nc.Agent.from_id("ag_1")
    assert coder.permission_mode == "approval-required"
    coder.update(permission_mode=None)
    assert body(patched.calls.last.request) == {"permission_mode": None}
    assert coder.permission_mode == "full-access"


def test_a_coding_agent_runs_docker_in_a_vm_of_its_size(api, client):
    made = api.post("/v1/agents").respond(json={**AGENT, "docker": True, "sandbox_size": "large"}, status_code=201)
    tester = nc.Agent.create("tester", instructions="Run the test suite.", harness="claude_code",
                             model_connection="claude", docker=True, sandbox_size="large")
    sent = body(made.calls.last.request)
    assert (sent["docker"], sent["sandbox_size"]) == (True, "large")
    assert (tester.docker, tester.sandbox_size) == (True, "large")
    patched = api.patch(f"/v1/agents/{AGENT['id']}").respond(json={**AGENT, "docker": False, "sandbox_size": None})
    tester.update(docker=False)
    assert body(patched.calls.last.request) == {"docker": False}
    assert (tester.docker, tester.sandbox_size) == (False, None)
    tester.update(sandbox_size=None)
    assert body(patched.calls.last.request) == {"sandbox_size": None}


def test_a_coding_agent_turns_app_testing_on_by_itself_unless_its_owner_says(api, client):
    made = api.post("/v1/agents").respond(json={**AGENT, "app_testing": "ask_first"}, status_code=201)
    coder = nc.Agent.create("coder", instructions="Keep checkout's tests green.", harness="claude_code",
                            model_connection="claude", app_testing="ask_first")
    assert body(made.calls.last.request)["app_testing"] == "ask_first"
    assert coder.app_testing == "ask_first"
    patched = api.patch(f"/v1/agents/{AGENT['id']}").respond(json={**AGENT, "app_testing": "never"})
    coder.update(app_testing="never")
    assert body(patched.calls.last.request) == {"app_testing": "never"}
    assert coder.app_testing == "never"


def test_an_update_sets_the_secrets_in_its_shell_by_id_or_name_and_setup(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.get("/v1/secrets").respond(json={"object": "list", "data": [
        {"object": "secret", "id": "4f1b2c3d-0000-4000-8000-000000000002", "name": "github", "keys": ["GH_TOKEN"]}],
        "next_cursor": None})
    patched = api.patch("/v1/agents/ag_1").respond(json=AGENT)
    nc.Agent.from_id("ag_1").update(secrets=["4f1b2c3d-0000-4000-8000-000000000001", "github"], setup=[])
    assert body(patched.calls.last.request) == {
        "secret_ids": ["4f1b2c3d-0000-4000-8000-000000000001", "4f1b2c3d-0000-4000-8000-000000000002"], "setup": []}
