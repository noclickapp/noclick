"""``Human.ask`` with ``pick`` (something in a connected account) and ``multiple`` (several choices): what the call
sends and how the answer reads, against the mocked transport."""

import noclick as nc
from platform_helpers import USER_ID, body, operation

CREATED = {**operation(op_id="op_h", kind="human.ask"),
           "request": {"id": "hr_1", "url": None, "delivered_via": ["web", "imessage"], "undelivered": []}}


def test_a_pick_names_the_connection_and_field_and_the_answer_its_value(api, client):
    create = api.post("/v1/humans/requests").respond(json=CREATED)
    api.get("/v1/operations/op_h/wait").respond(json=operation(
        op_id="op_h", kind="human.ask", status="succeeded",
        result={"choice": "Site", "value": "acme/site", "text": None},
    ))
    request = nc.Human.owner().ask(
        "Which repository should it open PRs in?",
        pick={"connection": "github", "field": "repository", "arguments": {"visibility": "private"}},
    )
    assert body(create.calls.last.request) == {
        "kind": "ask", "to": {"owner": True}, "message": "Which repository should it open PRs in?",
        "pick": {"connection": "github", "field": "repository", "arguments": {"visibility": "private"}},
        "via": "auto",
    }
    answer = request.wait()
    assert (answer.choice, answer.value, answer.choices, answer.values, str(answer)) == (
        "Site", "acme/site", [], [], "Site")


def test_a_connection_object_is_sent_by_its_id(api, client):
    create = api.post("/v1/humans/requests").respond(json=CREATED)
    slack = nc.Connection.from_id("con_9")
    with nc.as_user(USER_ID):
        nc.Human().ask("Which channel should it post in?", pick={"connection": slack, "field": "channel"})
    sent = create.calls.last.request
    assert body(sent)["pick"] == {"connection": "con_9", "field": "channel"}
    assert sent.headers["NoClick-User"] == USER_ID


def test_multiple_asks_for_several_and_the_answer_names_each(api, client):
    create = api.post("/v1/humans/requests").respond(json=CREATED)
    api.get("/v1/operations/op_h/wait").respond(json=operation(
        op_id="op_h", kind="human.ask", status="succeeded",
        result={"choices": ["Mon", "Wed"], "text": "mornings only"},
    ))
    request = nc.Human(email="ana@example.com").ask("Which days can you work?", options=["Mon", "Tue", "Wed"],
                                                    multiple=True)
    assert body(create.calls.last.request) == {
        "kind": "ask", "to": {"email": "ana@example.com"}, "message": "Which days can you work?",
        "options": ["Mon", "Tue", "Wed"], "multiple": True, "via": "auto",
    }
    answer = request.wait()
    assert (answer.choice, answer.choices, answer.text, str(answer)) == (
        None, ["Mon", "Wed"], "mornings only", "Mon, Wed")


def test_several_of_a_pick_read_back_with_their_values(api, client):
    create = api.post("/v1/humans/requests").respond(json=CREATED)
    api.get("/v1/operations/op_h/wait").respond(json=operation(
        op_id="op_h", kind="human.ask", status="succeeded",
        result={"choices": ["Site", "API"], "values": ["acme/site", "acme/api"], "text": None},
    ))
    answer = nc.Human.owner().ask("Which repositories?", pick={"connection": "github", "field": "repository"},
                                  multiple=True).wait()
    assert body(create.calls.last.request)["multiple"] is True
    assert (answer.choices, answer.values, answer.value) == (["Site", "API"], ["acme/site", "acme/api"], None)


def test_a_plain_question_sends_neither(api, client):
    create = api.post("/v1/humans/requests").respond(json=CREATED)
    nc.Human.owner().ask("Anything else?")
    sent = body(create.calls.last.request)
    assert "pick" not in sent and "multiple" not in sent
