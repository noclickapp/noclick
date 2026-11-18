"""Pausing a user's spending, the error a paused user's calls raise, and the message a deny rule
gives, against the mocked API."""

import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID, agent_row, body, listing, user_row

PAUSED = {
    "paused": True, "message": "You've used your credits.",
    "action": {"label": "Top up", "url": "https://acme.test/top-up/user_42"},
    "since": "2026-10-02T09:00:00Z", "held": 2, "paused_by": "key_1",
}


def test_pause_sends_what_the_user_is_told_and_reads_the_state_back(api, client):
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row(spending={"paused": False, "held": 0}))
    pause = api.post(f"/v1/users/{USER_ID}/spending/pause").respond(json=user_row(spending=PAUSED))
    user = nc.User.from_id(USER_ID)
    assert user.spending.paused is False and user.spending.action is None

    user.pause_spending(message="You've used your credits.",
                        action=("Top up", "https://acme.test/top-up/{{user.id}}"))
    assert body(pause.calls.last.request) == {
        "message": "You've used your credits.",
        "action": {"label": "Top up", "url": "https://acme.test/top-up/{{user.id}}"}}
    # Account-level: a pause never acts as the user it's about.
    assert "NoClick-User" not in pause.calls.last.request.headers
    spending = user.spending
    assert (spending.paused, spending.message, spending.action, spending.held, spending.paused_by) == (
        True, "You've used your credits.", ("Top up", "https://acme.test/top-up/user_42"), 2, "key_1")
    assert spending.since.hour == 9


def test_pause_with_the_console_default_sends_nothing_and_a_bad_action_never_leaves(api, client):
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row())
    pause = api.post(f"/v1/users/{USER_ID}/spending/pause").respond(json=user_row(spending=PAUSED))
    nc.User.from_id(USER_ID).pause_spending()
    assert body(pause.calls.last.request) == {}
    for bad in ("https://acme.test/top-up", ("Top up",), ("Top up", 42)):
        with pytest.raises(TypeError, match=r"\(label, url\)"):
            nc.User.from_id(USER_ID).pause_spending(action=bad)
    assert pause.call_count == 1


def test_resume_and_the_paused_filter(api, client):
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row(spending=PAUSED))
    resume = api.post(f"/v1/users/{USER_ID}/spending/resume").respond(
        json=user_row(spending={"paused": False, "held": 0}))
    user = nc.User.from_id(USER_ID)
    assert user.spending.held == 2
    assert user.resume_spending().spending.paused is False
    assert resume.call_count == 1

    users = api.get("/v1/users").respond(json=listing(user_row(spending=PAUSED)))
    paused = nc.User.list(spending="paused")
    assert [u.id for u in paused] == [USER_ID] and users.calls.last.request.url.params["spending"] == "paused"
    nc.User.list(status="active")
    assert "spending" not in users.calls.last.request.url.params


def test_a_paused_users_call_raises_with_their_message_apart_from_yours(api, client):
    api.get("/v1/agents/ag_1").respond(json=agent_row())
    api.post("/v1/agents/ag_1/messages").respond(402, json={"error": {
        "type": "spending_paused", "message": "Spending is paused for user_42.",
        "next_step": "Resume it with user.resume_spending() once they've paid.",
        "user_message": "You've used your credits.",
        "action": {"label": "Top up", "url": "https://acme.test/top-up/user_42"},
        "since": "2026-10-02T09:00:00Z"}})
    with pytest.raises(nc.SpendingPaused) as raised:
        nc.Agent.from_id("ag_1").message("Book the usual table", user=USER_ID)
    paused = raised.value
    assert (paused.status, paused.user_message, paused.action) == (
        402, "You've used your credits.", ("Top up", "https://acme.test/top-up/user_42"))
    assert paused.since.year == 2026 and "resume_spending" in paused.next_step


def test_a_deny_rule_carries_its_message_and_only_a_deny_rule_may(api, client):
    put = api.put("/v1/policy").mock(side_effect=lambda request: httpx.Response(200, json={
        "object": "policy", "user_id": None, **body(request)}))
    rule = nc.Rule("search", when='user.metadata.plan == "free"', message="Web search comes with Pro.")
    policy = nc.Policy.set(deny=[rule, {"tool": "gmail.*", "message": "Email is a Pro feature."}], user=None)
    assert body(put.calls.last.request)["deny"] == [
        {"tool": "search", "when": 'user.metadata.plan == "free"', "message": "Web search comes with Pro."},
        {"tool": "gmail.*", "message": "Email is a Pro feature."}]
    assert policy.deny[0].message == "Web search comes with Pro."
    with pytest.raises(ValueError, match="Only a deny rule has a message"):
        nc.Policy.set(allow=[rule], user=None)
