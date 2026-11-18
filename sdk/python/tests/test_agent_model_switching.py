"""Switching an agent's model connection: its rule (``model_switching``), the switch its own tool makes, the owner's
say-so for paid keys, and a plan's limit as its own error."""

import pytest

import noclick as nc
from platform_helpers import agent_row, body, listing

AGENT = agent_row(id="ag_1", name="atlas", harness="claude_code", model_connection="claude-work",
                  model_switching={"mode": "switch", "allowed": None},
                  switched_from={"connection": "claude-work", "name": "claude-work", "window": "five_hour",
                                 "resets_at": "2026-11-17T15:20:00+00:00"})
GRANT = {"id": "g_1", "agent_id": "ag_1", "connections": ["kestrel-api"], "scope": "standing", "source": "cited",
         "evidence": {"where": "channel", "channel_id": "ch_1", "message_id": "m_1", "at": "2026-11-17T15:10:00Z",
                      "quote": "you two use the Anthropic key", "link": None},
         "granted_by": {"type": "owner", "id": "u_1"}, "expires_at": None, "used_at": None, "revoked_at": None,
         "created_at": "2026-11-17T15:10:30Z"}


def test_its_rule_reads_back_and_is_sent_as_names(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    patch = api.patch("/v1/agents/ag_1").respond(json={**AGENT, "model_switching": {"mode": "stay", "allowed": None}})
    atlas = nc.Agent.from_id("ag_1")
    assert atlas.model_switching == {"mode": "switch", "allowed": None}
    assert atlas.switched_from["connection"] == "claude-work"
    # Only what's given is sent, so the rule's other part stays as it is: never a mode it wasn't given.
    atlas.update(model_switching=nc.ModelSwitching(mode="stay"))
    assert body(patch.calls.last.request) == {"model_switching": {"mode": "stay"}}
    atlas.update(model_switching={"allowed": ["claude-personal", "kestrel-api"]})
    assert body(patch.calls.last.request) == {"model_switching": {"allowed": ["claude-personal", "kestrel-api"]}}
    atlas.update(model_switching=nc.ModelSwitching(allowed=None))
    assert body(patch.calls.last.request) == {"model_switching": {"allowed": None}}
    atlas.update(model_switching=None)  # back to the default rule
    assert body(patch.calls.last.request) == {"model_switching": None}


def test_from_name_sets_only_a_part_of_the_rule_that_differs(api, client):
    api.get("/v1/agents").respond(json=listing(AGENT))
    patch = api.patch("/v1/agents/ag_1").respond(json=AGENT)
    nc.Agent.from_name("atlas", create_if_missing=True, instructions="hi",
                       model_switching=nc.ModelSwitching(mode="switch")).hydrate()
    assert patch.call_count == 0
    nc.Agent.from_name("atlas", create_if_missing=True, instructions="hi",
                       model_switching=nc.ModelSwitching(mode="stay")).hydrate()
    assert body(patch.calls.last.request) == {"model_switching": {"mode": "stay"}}


def test_a_switch_names_its_connection_and_cites_the_owners_words(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    switch = api.post("/v1/agents/ag_1/model/switch").respond(json={
        "status": "switched", "connection": "kestrel-api", "harness": "claude_code", "pays": "per_use"})
    done = nc.Agent.from_id("ag_1").switch_model(
        "kestrel-api", reason="told to in #usage", scope="standing",
        evidence={"channel_id": "ch_1", "message_id": "m_1", "quote": "you two use the Anthropic key"})
    assert done["status"] == "switched"
    assert body(switch.calls.last.request) == {
        "connection": "kestrel-api", "reason": "told to in #usage", "scope": "standing",
        "evidence": {"channel_id": "ch_1", "message_id": "m_1", "quote": "you two use the Anthropic key"}}


def test_the_owners_say_so_is_listed_given_and_taken_back(api, client):
    """The grants are read with the agent and taken back with its update (``revoke_model_grants``)."""
    api.get("/v1/agents/ag_1").respond(json={**AGENT, "model_grants": [GRANT]})
    given = api.post("/v1/agents/ag_1/model/grants").respond(201, json={**GRANT, "source": "owner"})
    revoked = api.patch("/v1/agents/ag_1").respond(json={
        **AGENT, "model_grants": [{**GRANT, "revoked_at": "2026-11-18T09:00:00Z"}]})
    atlas = nc.Agent.from_id("ag_1")
    [grant] = atlas.model_grants()
    assert (grant.scope, grant.source, grant.evidence["quote"]) == ("standing", "cited", "you two use the Anthropic key")
    assert atlas.grant_model_switch(["kestrel-api"]).source == "owner"
    assert body(given.calls.last.request) == {"connections": ["kestrel-api"], "scope": "standing"}
    assert atlas.revoke_model_grant(grant).revoked_at == "2026-11-18T09:00:00Z"
    assert body(revoked.calls.last.request) == {"revoke_model_grants": ["g_1"]}


def test_a_plans_limit_is_its_own_error_with_when_its_back():
    err = nc.exceptions.error_from_payload({"error": {
        "type": "plan_limit_reached", "message": "Your Claude plan (claude-work) is used up until 3:20 PM.",
        "reason": "plan_limit", "connection": "claude-work", "window": "five_hour",
        "resets_at": "2026-11-17T15:20:00+00:00", "then": {"waiting_until": "2026-11-17T15:20:00+00:00"}}}, status=429)
    assert isinstance(err, nc.PlanLimitReached)
    assert (err.window, err.resets_at, err.then["waiting_until"]) == (
        "five_hour", "2026-11-17T15:20:00+00:00", "2026-11-17T15:20:00+00:00")
    with pytest.raises(nc.PlanLimitReached):
        raise err
