import json

import noclick as nc

MADE = {
    "object": "agent_for_apps", "created": True,
    "agent": {"id": "agt_1", "name": "Roblox agent", "harness": "hermes", "model": "openrouter/~openai/gpt-luna-latest",
              "model_connection": "roblox-agent-model"},
    "channel": {"id": "ch_1", "name": "roblox"},
    "needs": [{"kind": "app", "integration": "roblox", "node_type": "automation-roblox", "label": "Roblox",
               "description": "Manage Roblox experiences", "connected": False},
              {"kind": "model", "connected": False}],
}


def test_an_agent_for_apps_is_made_for_the_account_with_what_it_still_needs(api, client):
    route = api.post("/v1/agents/for_apps").respond(json=MADE)

    made = nc.Agent.for_apps(["roblox"], harness="hermes")

    assert json.loads(route.calls.last.request.content) == {"apps": ["roblox"], "harness": "hermes"}
    # For the account itself, never a user.
    assert "noclick-user" not in {k.lower() for k in route.calls.last.request.headers}
    assert (made.agent.id, made.channel, made.created) == ("agt_1", {"id": "ch_1", "name": "roblox"}, True)
    assert [(n.kind, n.label, n.connected) for n in made.needs] == [("app", "Roblox", False), ("model", None, False)]
