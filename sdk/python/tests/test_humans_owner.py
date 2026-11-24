import pytest

import noclick as nc
from platform_helpers import USER_ID, body, operation

AGENT_ID = "8b7c5e2a-4d1f-4c3e-9a6b-1f2e3d4c5b6a"


def test_the_owner_is_reached_as_the_account_on_the_app_they_text_on(api, client):
    send = api.post("/v1/humans/requests").respond(json={
        **operation(op_id="op_n", kind="human.notify", status="succeeded"),
        "request": {"id": "hr_1", "delivered_via": ["web", "whatsapp"], "undelivered": []},
    })
    with nc.as_user(USER_ID):  # the owner is the account's person, never a user's
        request = nc.Human.owner().notify("The site is live", via="whatsapp")
    assert body(send.calls.last.request) == {
        "kind": "notify", "to": {"owner": True}, "message": "The site is live", "via": ["whatsapp"],
    }
    assert "NoClick-User" not in send.calls.last.request.headers
    assert request.delivered_via == ["web", "whatsapp"]


def test_answer_with_routes_the_owners_texts_and_none_hands_them_back(api, client):
    route = api.post("/v1/humans/owner/answer").respond(json={"object": "human_answer", "person": "owner",
                                                              "agent_id": AGENT_ID, "conversation": "owner"})
    owner = nc.Human.owner()
    assert owner.answer_with(AGENT_ID, conversation="owner") is owner
    assert body(route.calls.last.request) == {"agent_id": AGENT_ID, "conversation": "owner"}
    owner.answer_with(None)
    assert body(route.calls.last.request) == {"agent_id": None}

    api.get("/v1/humans/owner/answer").respond(json={"object": "human_answer", "person": "owner", "agent_id": AGENT_ID})
    assert owner.answering().id == AGENT_ID
    with pytest.raises(ValueError):
        nc.Human(email="ana@example.com").answer_with(AGENT_ID)


def test_reach_reads_noclicks_numbers_and_whether_a_phone_is_linked_as_the_account(api, client):
    read = api.get("/v1/humans/owner/reach").respond(json={
        "object": "owner_reach", "phone_linked": True,
        "lines": [{"app": "whatsapp", "number": "+14155550100"}, {"app": "imessage", "number": "+14155550101"}],
    })
    with nc.as_user(USER_ID):  # where the owner texts NoClick is the account's, never a user's
        reach = nc.Human.owner().reach()
    assert "NoClick-User" not in read.calls.last.request.headers
    assert reach == nc.OwnerReach(lines=[nc.OwnerLine(app="whatsapp", number="+14155550100"),
                                         nc.OwnerLine(app="imessage", number="+14155550101")], phone_linked=True)
    api.get("/v1/humans/owner/reach").respond(json={"object": "owner_reach", "lines": [], "phone_linked": False,
                                                    "email": {"address": "maya@noclick.email", "paused": True,
                                                              "from_anyone": False}})
    assert nc.Human.owner().reach() == nc.OwnerReach(lines=[], phone_linked=False, email=nc.OwnerEmailAddress(
        address="maya@noclick.email", paused=True, from_anyone=False))
    placed = api.put("/v1/humans/owner/timezone").respond(json={"object": "owner_timezone", "timezone": "Europe/London"})
    nc.Human.owner().set_timezone("Europe/London")
    assert body(placed.calls.last.request) == {"timezone": "Europe/London"}
    with pytest.raises(ValueError):
        nc.Human(email="ana@example.com").reach()


def test_the_owner_adds_an_email_by_code(api, client):
    sent = api.post("/v1/humans/owner/email").respond(json={"object": "owner_email", "status": "code_sent",
                                                           "email": "maya@morrowbakery.com", "expires_in_minutes": 15})
    owner = nc.Human.owner()
    with nc.as_user(USER_ID):  # the owner's email is the account's, never a user's
        assert owner.add_email("maya@morrowbakery.com") is None
    assert body(sent.calls.last.request) == {"email": "maya@morrowbakery.com"}
    assert "NoClick-User" not in sent.calls.last.request.headers
    confirm = api.post("/v1/humans/owner/email/confirm").respond(json={
        "object": "owner_email", "status": "added", "email": "maya@morrowbakery.com", "merged": True})
    assert owner.confirm_email("482913") == nc.OwnerEmail(email="maya@morrowbakery.com", status="added", merged=True)
    assert body(confirm.calls.last.request) == {"code": "482913"}
    with pytest.raises(ValueError):
        nc.Human(email="ana@example.com").add_email("ana@example.com")


def test_an_inbox_and_a_number_take_a_conversation_template(api, client):
    created = api.post("/v1/inboxes").respond(json={"object": "inbox", "id": "inb_1", "address": "a@noclick.email",
                                                    "conversation": "mail-{sender}"})
    inbox = nc.Inbox.create(local_part="a", conversation="mail-{sender}")
    assert body(created.calls.last.request)["conversation"] == "mail-{sender}" and inbox.conversation == "mail-{sender}"
    patched = api.patch("/v1/inboxes/inb_1").respond(json={"object": "inbox", "id": "inb_1",
                                                           "address": "a@noclick.email", "conversation": None})
    inbox.update(conversation=None)
    assert body(patched.calls.last.request) == {"conversation": None}

    answered = api.post("/v1/phone_numbers/pn_1/answer").respond(json={"object": "phone_number", "id": "pn_1"})
    nc.PhoneNumber.from_id("pn_1").answer_with(AGENT_ID, conversation="owner")
    assert body(answered.calls.last.request) == {"agent_id": AGENT_ID, "conversation": "owner"}
