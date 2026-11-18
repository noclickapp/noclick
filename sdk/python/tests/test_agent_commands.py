"""A coding agent's own commands from a chat: the list its harness offers, a command sent in place of text, and a
message steered into the running turn or queued behind it."""

import pytest

import noclick as nc
from platform_helpers import agent_row, body

AGENT = agent_row(id="ag_1", name="coder", harness="claude_code")
TURN = {"object": "operation", "id": "op_1", "kind": "agent.message", "status": "queued"}


def test_commands_reads_what_the_harness_offers_and_how_fresh_it_is(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    route = api.get("/v1/agents/ag_1/conversations/main%2F1/commands").respond(json={
        "object": "agent_commands", "harness": "claude_code",
        "commands": [{"name": "compact", "description": "Compact the thread", "argument_hint": "<instructions>",
                      "source": "harness", "aliases": []}],
        "skills": [{"name": "pdf", "description": "Read PDFs"}],
        "capabilities": {"commands": True, "skills": False, "compact": True, "review": False, "goal": False,
                         "init": False, "steer": True, "queue": True},
        "not_supported": {}, "withheld": ["config", "mcp"],
        "mapped": [{"name": "model", "to": "model"}], "as_of": "2026-11-09T10:05:00Z",
        "read_from": "this_conversation"})
    listed = nc.Agent.from_id("ag_1").commands("main/1")
    assert route.called
    assert listed.commands == [nc.AgentCommand("compact", "Compact the thread", "<instructions>", "harness", [])]
    assert listed.skills == [{"name": "pdf", "description": "Read PDFs"}]
    assert (listed.capabilities["compact"], listed.capabilities["review"]) == (True, False)
    assert listed.withheld == ["config", "mcp"]
    assert listed.mapped == [{"name": "model", "to": "model"}]
    assert listed.as_of.isoformat().startswith("2026-11-09T10:05") and listed.read_from == "this_conversation"


def test_a_command_goes_in_place_of_text_never_as_text(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    send = api.post("/v1/agents/ag_1/messages").respond(202, json=TURN)
    coder = nc.Agent.from_id("ag_1")
    assert coder.send(conversation="main", command={"name": "compact", "arguments": "keep the API notes"}).id == "op_1"
    assert body(send.calls.last.request) == {"command": {"name": "compact", "arguments": "keep the API notes"},
                                             "conversation": "main"}
    coder.send(conversation="main", command={"name": "review"}, delivery="queue")
    assert body(send.calls.last.request) == {"command": {"name": "review"}, "delivery": "queue",
                                             "conversation": "main"}
    with pytest.raises(TypeError, match="text or a command"):
        coder.send("hi", command={"name": "compact"})
    with pytest.raises(TypeError, match="text or a command"):
        coder.send()


def test_a_message_steered_into_the_running_turn_or_queued_behind_it(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    send = api.post("/v1/agents/ag_1/messages").respond(202, json={**TURN, "kind": "agent.ask"})
    coder = nc.Agent.from_id("ag_1")
    coder.send("also update the README", conversation="main", delivery="steer")
    assert body(send.calls.last.request) == {"text": "also update the README", "delivery": "steer",
                                             "conversation": "main"}
    coder.send("then open a PR", conversation="main", delivery="queue")
    assert body(send.calls.last.request) == {"text": "then open a PR", "delivery": "queue", "conversation": "main"}


def test_history_says_which_message_ran_a_command(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.get("/v1/agents/ag_1/conversations/main").respond(json={"object": "conversation", "next_cursor": None,
                                                                "messages": [
        {"role": "user", "text": "/compact", "command": {"name": "compact", "arguments": ""},
         "created_at": "2026-11-09T10:00:00Z"},
        {"role": "user", "text": "hello", "created_at": "2026-11-09T10:01:00Z"}]})
    ran, said = nc.Agent.from_id("ag_1").history("main")
    assert ran.command == {"name": "compact", "arguments": ""} and said.command is None
