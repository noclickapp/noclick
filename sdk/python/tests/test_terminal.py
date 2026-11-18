"""Take-over: a coding agent's conversation as its harness's own terminal. ``take_over`` opens it (a single-use token
for its websocket), ``terminal`` reads where it stands, ``Terminal.hand_back`` gives it back."""

import noclick as nc
from platform_helpers import agent_row, body

AGENT = agent_row(id="ag_1", name="coder", harness="claude_code", model="claude-sonnet-4-5")
TAKEN = {"object": "terminal", "agent_id": "ag_1", "conversation": "main", "harness": "claude_code",
         "state": "person", "waiting_for_turn": False, "since": "2026-10-29T10:01:00Z",
         "ends_at": "2026-10-29T13:57:00Z", "idle_limit_s": 900, "detached_limit_s": 300, "ended_because": None,
         "url": "wss://api.test/v1/terminals/attach", "token": "tok_1", "token_expires_at": "2026-10-29T10:03:00Z"}
READ = {k: v for k, v in TAKEN.items() if k not in ("url", "token", "token_expires_at")}


def test_take_over_read_and_hand_back(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    take = api.post("/v1/agents/ag_1/conversations/main/terminal").respond(json=TAKEN)
    read = api.get("/v1/agents/ag_1/conversations/main/terminal").respond(json=READ)
    back = api.delete("/v1/agents/ag_1/conversations/main/terminal").respond(
        json={**READ, "state": "agent", "ended_because": "handed_back"})
    coder = nc.Agent.from_id("ag_1")

    terminal = coder.take_over("main", interrupt=True, cols=120, rows=36)
    assert body(take.calls.last.request) == {"interrupt": True, "cols": 120, "rows": 36}
    assert isinstance(terminal, nc.Terminal)
    assert (terminal.state, terminal.harness, terminal.url, terminal.token, terminal.idle_limit_s) == (
        "person", "claude_code", "wss://api.test/v1/terminals/attach", "tok_1", 900)
    assert terminal.ends_at.isoformat() == "2026-10-29T13:57:00+00:00"
    coder.take_over("main")
    assert body(take.calls.last.request) == {}  # its turn finishes first unless asked to interrupt

    now = coder.terminal("main")
    assert read.call_count == 1 and (now.state, now.token) == ("person", None)
    assert repr(now) == "Terminal(agent_id='ag_1', conversation='main', state='person')"

    now.hand_back()
    assert back.call_count == 1 and (now.state, now.ended_because) == ("agent", "handed_back")


def test_a_conversation_key_is_one_path_segment(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    take = api.post("/v1/agents/ag_1/conversations/user%3A42%2Fmain/terminal").respond(
        json={**TAKEN, "conversation": "user:42/main"})
    terminal = nc.Agent.from_id("ag_1").take_over("user:42/main")
    assert take.call_count == 1 and terminal.conversation == "user:42/main"
    back = api.delete("/v1/agents/ag_1/conversations/user%3A42%2Fmain/terminal").respond(
        json={**READ, "conversation": "user:42/main", "state": "agent"})
    terminal.hand_back()
    assert back.call_count == 1
