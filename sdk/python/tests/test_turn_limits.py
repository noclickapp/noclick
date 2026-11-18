"""An agent's turn limits: how far one of its turns goes (steps, usd, minutes), sent as given and kept in step
by ``from_name``, cleared with ``None``; a reply names the limit that ended its turn."""

import noclick as nc
from platform_helpers import agent_row, body, listing, operation

AGENT = agent_row(id="ag_1", name="builder")


def test_create_sends_the_limits_given(api, client):
    create = api.post("/v1/agents").respond(json={**AGENT, "turn_limits": {"steps": 100}})
    agent = nc.Agent.create("builder", instructions="Ship sites.", turn_limits={"steps": 100, "usd": None})
    assert body(create.calls.last.request) == {"name": "builder", "instructions": "Ship sites.",
                                               "turn_limits": {"steps": 100}}
    assert agent.turn_limits == {"steps": 100}


def test_from_name_converges_the_limits_and_none_clears_them(api, client):
    api.get("/v1/agents").respond(json=listing({**AGENT, "turn_limits": {"steps": 100}}))
    patch = api.patch("/v1/agents/ag_1").respond(json=AGENT)
    nc.Agent.from_name("builder", create_if_missing=True, instructions=AGENT["instructions"],
                       turn_limits={"steps": 100}).hydrate()
    assert not patch.called  # as defined: nothing to change

    nc.Agent.from_name("builder", create_if_missing=True, instructions=AGENT["instructions"],
                       turn_limits={"steps": 150, "minutes": 30}).hydrate()
    assert body(patch.calls.last.request) == {"turn_limits": {"steps": 150, "minutes": 30}}
    nc.Agent.from_name("builder", create_if_missing=True, instructions=AGENT["instructions"],
                       turn_limits=None).hydrate()
    assert body(patch.calls.last.request) == {"turn_limits": None}


def test_update_sends_the_limits_and_none_goes_back_to_the_defaults(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    patch = api.patch("/v1/agents/ag_1").respond(json={**AGENT, "turn_limits": {"steps": 150, "usd": 3}})
    agent = nc.Agent.from_id("ag_1").update(turn_limits={"steps": 150, "usd": 3})
    assert body(patch.calls.last.request) == {"turn_limits": {"steps": 150, "usd": 3}}
    assert agent.turn_limits == {"steps": 150, "usd": 3}
    nc.Agent.from_id("ag_1").update(turn_limits=None)
    assert body(patch.calls.last.request) == {"turn_limits": None}


def test_a_reply_names_the_limit_that_ended_its_turn(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.post("/v1/agents/ag_1/messages").respond(json=operation(
        "op_m", "agent.message", "succeeded", result={"text": "Two pages are up; the rest is next.",
                                                      "ended_by": "steps"}))
    assert nc.Agent.from_id("ag_1").message("Build the site").ended_by == "steps"
    api.post("/v1/agents/ag_1/messages").respond(json=operation("op_n", "agent.message", "succeeded",
                                                                result={"text": "Done."}))
    assert nc.Agent.from_id("ag_1").message("hi").ended_by is None
