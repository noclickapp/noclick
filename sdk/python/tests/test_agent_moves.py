"""Moves from a laptop: ``AgentMove.create`` makes one (its code and prompt only then), a read follows it, ``cancel``
calls it off; the moving agent redeems the code for the move's own key and carries its session, files, env, MCP
servers, skills, memories and note with it, then finishes it."""

import httpx
import pytest

import noclick as nc
from platform_helpers import BASE, body

MOVE = {"object": "agent_move", "id": "mv_1", "status": "waiting", "workspace_id": "ws_1",
        "draft": {"name": "Docs fixer"}, "source": None, "steps": [], "agent_id": None, "conversation": None,
        "error": None, "guide_url": "https://noclick.com/move.md", "expires_at": "2026-11-10T10:30:00Z",
        "created_at": "2026-11-10T10:00:00Z",
        "arrived": {"session": None, "repo": None, "files": [], "env": [], "mcp_servers": [], "skills": [],
                    "memories": [], "note": None, "instructions": None}}
MADE = {**MOVE, "code": "nc_move_abc", "prompt": "Move this session to NoClick: read https://noclick.com/move.md …"}


def test_make_follow_and_call_off_a_move(api, client):
    create = api.post("/v1/agents/moves").respond(201, json=MADE)
    move = nc.AgentMove.create(name="Docs fixer", workspace="ws_1", harness="claude_code", machine="mc_1")
    assert body(create.calls.last.request) == {"name": "Docs fixer", "workspace_id": "ws_1", "harness": "claude_code",
                                               "machine_id": "mc_1"}
    assert (move.id, move.status, move.code) == ("mv_1", "waiting", "nc_move_abc")
    assert move.prompt.startswith("Move this session") and move.guide_url == "https://noclick.com/move.md"

    api.get("/v1/agents/moves/mv_1").respond(json={**MOVE, "status": "done", "agent_id": "ag_1",
                                                   "conversation": "moved-6f1e2d3c"})
    read = nc.AgentMove.from_id("mv_1")
    assert (read.status, read.agent_id, read.conversation, read.code) == ("done", "ag_1", "moved-6f1e2d3c", None)
    assert repr(read) == "AgentMove(id='mv_1', status='done')"

    cancel = api.post("/v1/agents/moves/mv_1/cancel").respond(json={**MOVE, "status": "canceled"})
    assert nc.AgentMove.from_id("mv_1").cancel().status == "canceled" and cancel.call_count == 1


def test_the_moving_agent_carries_what_it_chose(api, client):
    redeem = api.post("/v1/moves/redeem").respond(200, text="nk_live_movekey\n")
    assert nc.AgentMove.redeem("nc_move_abc", host="ana-mbp", base_url=BASE) == "nk_live_movekey"
    assert redeem.calls.last.request.content == b"code=nc_move_abc&host=ana-mbp"

    moving_view = {**MOVE, "status": "moving", "lands_as": {"name": "Docs fixer", "harness": "claude_code",
                                                            "cwd": "/workspace/acme"},
                   "endpoints": ["GET /v1/moves/current — The move this key carries"]}
    current = api.get("/v1/moves/current").respond(json=moving_view)
    moving = nc.AgentMove.current()
    assert moving.lands_as["cwd"] == "/workspace/acme"
    assert moving.endpoints == ["GET /v1/moves/current — The move this key carries"]

    routes = {
        "source": api.put("/v1/moves/current/source").respond(json=moving_view),
        "session": api.put("/v1/moves/current/session").respond(json=moving_view),
        "files": api.put("/v1/moves/current/files").respond(json=moving_view),
        "consent": api.put("/v1/moves/current/consent").respond(json=moving_view),
        "secret": api.put("/v1/moves/current/secrets/linear-token").respond(json=moving_view),
        "setup": api.put("/v1/moves/current/setup").respond(json=moving_view),
        "checkout": api.put("/v1/moves/current/checkout").respond(json=moving_view),
        "mcp": api.put("/v1/moves/current/mcp_servers/deepwiki").respond(json=moving_view),
        "skill": api.put("/v1/moves/current/skills/release-notes").respond(json=moving_view),
        "memory": api.put("/v1/moves/current/memories/deploy-steps").respond(json=moving_view),
        "note": api.put("/v1/moves/current/note").respond(json=moving_view),
        "instructions": api.put("/v1/moves/current/instructions").respond(json=moving_view),
    }
    repo = api.post("/v1/moves/current/repo").respond(json={
        "object": "move_repo", "repo_id": "rp_1", "name": "acme", "branch": "laptop/ana-mbp-20261110",
        "path": "acme", "url": "https://x:token@git.test/acme.git", "expires_at": "2026-11-10T10:10:00Z",
        "cwd": "/workspace/acme"})
    running = {**moving_view, "status": "finishing", "next_step": "Read the move again in a few seconds.",
               "steps": [{"name": "secrets", "label": "Bringing its secrets", "status": "running"}]}
    finish = api.post("/v1/moves/current/finish").respond(json={**running, "steps": []})

    moving.set_source(harness="claude_code", host="ana-mbp", cwd="/Users/ana/code/acme", session_id="s1")
    assert body(routes["source"].calls.last.request) == {"harness": "claude_code", "host": "ana-mbp",
                                                         "cwd": "/Users/ana/code/acme", "session_id": "s1"}
    moving.upload_session(b"TAR", harness="claude_code", cwd="/Users/ana/code/acme", session_id="s1")
    sent = routes["session"].calls.last.request
    assert sent.content == b"TAR" and httpx.URL(str(sent.url)).params["harness"] == "claude_code"
    assert moving.repo()["branch"] == "laptop/ana-mbp-20261110" and repo.call_count == 1
    moving.put_file("notes/spec.md", b"# Spec")
    assert httpx.URL(str(routes["files"].calls.last.request.url)).params["path"] == "notes/spec.md"
    asked = [{"name": "linear-token", "kind": "Linear API key", "to": "env LINEAR_API_KEY"}]
    moving.consent(asked, confirmed=True)
    assert body(routes["consent"].calls.last.request) == {"secrets": asked, "confirmed": True}
    moving.put_secret("linear-token", "lin_x", to={"env": "LINEAR_API_KEY"})
    assert body(routes["secret"].calls.last.request) == {"value": "lin_x", "to": {"env": "LINEAR_API_KEY"}}
    moving.set_setup(["npm install -g @linear/cli"])
    assert body(routes["setup"].calls.last.request) == {"commands": ["npm install -g @linear/cli"]}
    moving.set_checkout("https://github.com/acme/web.git", "noclick/ana", secret="linear-token")
    assert body(routes["checkout"].calls.last.request) == {"url": "https://github.com/acme/web.git",
                                                           "branch": "noclick/ana", "secret": "linear-token"}
    plan = api.post("/v1/moves/current/plan_link").respond(json={"object": "plan_link", "url": "https://x.test/p"})
    assert moving.plan_link()["url"] == "https://x.test/p" and plan.call_count == 1
    moving.add_mcp_server("deepwiki", "https://mcp.deepwiki.com/mcp")
    assert body(routes["mcp"].calls.last.request) == {"url": "https://mcp.deepwiki.com/mcp", "transport": "http",
                                                      "headers": {}}
    connector = api.put("/v1/moves/current/mcp_servers/notion").respond(json=moving_view)
    moving.add_mcp_server("notion", "https://mcp.notion.com/mcp", sign_in="browser")
    assert body(connector.calls.last.request) == {"url": "https://mcp.notion.com/mcp", "transport": "http",
                                                  "headers": {}, "sign_in": "browser"}
    moving.add_skill("release-notes", b"SKILLTAR")
    moving.add_memory("deploy-steps", "Deploy with make ship.", description="How this repo deploys")
    assert body(routes["memory"].calls.last.request) == {"content": "Deploy with make ship.",
                                                         "description": "How this repo deploys"}
    moving.set_note("Next: a test for the third retry.")
    assert routes["note"].calls.last.request.content == b"Next: a test for the third retry."
    moving.set_instructions("Be terse.")
    # The finish answers at once and runs on NoClick: the move is read until it ends, a failed step raising its own
    # error (here a carried key the session's harness doesn't run on).
    refusal = {"type": "conflict", "message": "The carried OpenRouter key doesn't run Claude Code here.",
               "next_step": 'Finish again on one it runs: {"harness": "opencode"}.', "runs_on": ["opencode"]}
    current.side_effect = [httpx.Response(200, json=running), httpx.Response(200, json={
        **moving_view, "status": "failed", "error": refusal["message"], "next_step": refusal["next_step"],
        "steps": [{"name": "secrets", "label": "Bringing its secrets", "status": "done"},
                  {"name": "agent", "label": "Making it", "status": "failed", "error": refusal["message"],
                   "failure": refusal}]})]
    client.sleeps.clear()
    with pytest.raises(nc.Conflict) as refused:
        moving.finish()
    assert body(finish.calls.last.request) == {} and client.sleeps == [nc.agent_move.FINISH_POLL_S] * 2
    assert (refused.value.next_step, refused.value.runs_on) == (refusal["next_step"], ["opencode"])
    # Finished again on one it does.
    current.side_effect = [httpx.Response(200, json={**moving_view, "status": "done", "agent_id": "ag_1"})]
    done = moving.finish(harness="opencode", model="openrouter/anthropic/claude-sonnet-4.5")
    assert (done.status, done.agent_id) == ("done", "ag_1")
    assert body(finish.calls.last.request) == {"harness": "opencode", "model": "openrouter/anthropic/claude-sonnet-4.5"}
    current.side_effect = None
    assert moving.finish(wait=False).status == "finishing"
    # Asked whether it has no tool servers or skills, it says so outright.
    asking = api.post("/v1/moves/current/finish").respond(json={**moving_view, "question": "No MCP server and no skill?"})
    assert nc.AgentMove.current().finish().question == "No MCP server and no skill?"
    nc.AgentMove.current().finish(none=["mcp_servers", "skills"])
    assert body(asking.calls.last.request) == {"none": ["mcp_servers", "skills"]}
    # The move's own calls never name a user: its key's scope is the move's.
    assert all("NoClick-User" not in r.calls.last.request.headers for r in routes.values())


def test_the_person_signs_in_to_a_server_the_move_carried_needing_it(api, client):
    carried = {"name": "notion", "to": {"tool_server": "notion"}, "url": "https://mcp.notion.com/mcp",
               "needs_sign_in": False, "step": "mcp-1", "reused": False, "credential_id": "cr_1"}
    done = {**MOVE, "status": "done", "agent_id": "ag_1", "arrived": {**MOVE["arrived"], "carried": [carried]}}
    route = api.post("/v1/agents/moves/mv_1/sign_ins/notion").respond(json=done)
    move = nc.AgentMove.from_id("mv_1").connect_sign_in("notion", "cr_1")
    assert body(route.calls.last.request) == {"credential_id": "cr_1"}
    assert move.arrived["carried"] == [carried]


def test_an_agent_says_where_a_move_made_it_from(api, client):
    from platform_helpers import agent_row

    moved = {"move_id": "mv_1", "host": "ana-mbp", "folder": "/Users/ana/code/acme", "at": "2026-11-10T10:30:00+00:00"}
    api.get("/v1/agents/ag_1").respond(json=agent_row(id="ag_1", name="coder", moved_from=moved))
    api.get("/v1/agents/ag_2").respond(json=agent_row(id="ag_2", name="other", moved_from=None))
    assert nc.Agent.from_id("ag_1").moved_from == moved
    assert nc.Agent.from_id("ag_2").moved_from is None
