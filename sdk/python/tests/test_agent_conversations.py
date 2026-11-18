"""A long conversation read back a page at a time, and a question to the owner withdrawn once it's answered another
way."""

import pytest

import noclick as nc
from platform_helpers import agent_row, body

AGENT = agent_row(id="ag_1", name="support")


def _message(text, at):
    return {"role": "user", "text": text, "created_at": f"2026-10-15T10:{at:02d}:00Z"}


def test_history_reads_a_long_thread_back_a_page_at_a_time(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    route = api.get("/v1/agents/ag_1/conversations/ticket-1841")
    route.respond(json={"object": "conversation", "messages": [_message("third", 3), _message("fourth", 4)],
                        "next_cursor": "2"})
    support = nc.Agent.from_id("ag_1")
    page = support.history_page("ticket-1841", limit=2)
    assert isinstance(page, nc.Page) and [m.text for m in page.data] == ["third", "fourth"]
    assert page.next_cursor == "2"
    assert dict(route.calls.last.request.url.params) == {"limit": "2"}

    route.respond(json={"object": "conversation", "messages": [_message("first", 1), _message("second", 2)],
                        "next_cursor": None})
    earlier = support.history_page("ticket-1841", limit=2, before=page.next_cursor)
    assert dict(route.calls.last.request.url.params) == {"limit": "2", "before": "2"}
    assert ([m.text for m in earlier.data], earlier.next_cursor) == (["first", "second"], None)

    # history() is the page's messages; without limit, the whole thread as before.
    assert [m.text for m in support.history("ticket-1841", limit=2, before="2")] == ["first", "second"]
    support.history("ticket-1841")
    assert dict(route.calls.last.request.url.params) == {}


def test_a_question_to_the_owner_is_withdrawn_with_a_note(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    withdraw = api.post("/v1/agents/ag_1/conversations/ticket%2F1841/withdraw_question").respond(json={
        "object": "question_withdrawal", "agent_id": "ag_1", "conversation": "ticket/1841",
        "withdrawn": ["May I refund order 1841?"]})
    support = nc.Agent.from_id("ag_1")
    with nc.as_user("user_42"):  # only the account withdraws one: no user goes with the call
        withdrawn = support.withdraw_question("ticket/1841", "Ana approved the refund on the phone; it's issued.")
    assert withdrawn == ["May I refund order 1841?"]
    assert body(withdraw.calls.last.request) == {"note": "Ana approved the refund on the phone; it's issued."}
    assert "NoClick-User" not in withdraw.calls.last.request.headers

    support.withdraw_question("ticket/1841", "Handled by email.", question_id="req_2")
    assert body(withdraw.calls.last.request) == {"note": "Handled by email.", "question_id": "req_2"}

    api.post("/v1/agents/ag_1/conversations/ticket%2F1841/withdraw_question").respond(409, json={"error": {
        "type": "conflict", "message": "No question to the owner waits in this conversation."}})
    with pytest.raises(nc.Conflict, match="No question"):
        support.withdraw_question("ticket/1841", "Already answered.")


def test_a_notification_passing_on_a_spaces_news_names_its_space(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    space = {"workspace_id": "ws_1", "name": "Launch", "label": "NoClick · Launch"}
    api.get("/v1/agents/ag_1/conversations/owner").respond(json={"object": "conversation", "next_cursor": None, "messages": [
        {"role": "assistant", "text": "The import failed twice.", "notification": True, "space": space,
         "created_at": "2026-11-11T10:00:00Z"},
        {"role": "assistant", "text": "Your site is live.", "notification": True, "created_at": "2026-11-11T10:01:00Z"},
        {"role": "assistant", "text": "Done.", "created_at": "2026-11-11T10:02:00Z"},
    ]})
    said = nc.Agent.from_id("ag_1").history("owner")
    assert [(m.notification, m.space) for m in said] == [(True, space), (True, None), (False, None)]
