"""A human request's page through its link (``noclick.HumanRequestLink``): it reads and answers with the link alone,
never a key, the link's own key (``k``) going along with every call, and a request the link can't open raises
``noclick.NotFound``."""

import json

import httpx
import pytest
import respx

import noclick as nc
from platform_helpers import BASE

PATH = "/v1/public/human_requests/hr_1"
PAGE = {"id": "hr_1", "kind": "approve", "status": "pending", "message": "Buy +1 415 555 0100 for $1.15 a month?",
        "expires_at": "2026-11-26T10:00:00+00:00", "brand": {"name": "NoClick"}, "approval": {"id": "ap_1"}}


def test_reads_and_answers_with_the_link_alone_its_key_going_along():
    with respx.mock(base_url=BASE) as api:
        read = api.get(PATH).respond(json=PAGE)
        answered = api.post(f"{PATH}/answer").respond(json={**PAGE, "status": "answered"})
        link = nc.HumanRequestLink("hr_1", key="k-1", base_url=BASE)
        page = link.read()
        assert (page.id, page.kind, page.status, page.message) == ("hr_1", "approve", "pending", PAGE["message"])
        assert page.expires_at.isoformat() == "2026-11-26T10:00:00+00:00" and page.raw["approval"] == {"id": "ap_1"}
        assert read.calls.last.request.url.params["k"] == "k-1"
        assert "authorization" not in read.calls.last.request.headers
        assert link.answer({"decision": "approve"})["status"] == "answered"
        sent = answered.calls.last.request
        assert sent.url.params["k"] == "k-1" and "authorization" not in sent.headers
        assert json.loads(sent.content) == {"decision": "approve"}


def test_connects_replies_and_hands_back_and_one_the_link_cant_open_is_not_found():
    with respx.mock(base_url=BASE) as api:
        connected = api.post(f"{PATH}/connect").respond(json={"url": "https://accounts.example.test/sign-in"})
        replied = api.post(f"{PATH}/reply").respond(json=PAGE)
        back = api.post(f"{PATH}/hand_back").respond(json=PAGE)
        api.get("/v1/public/human_requests/hr_2").mock(return_value=httpx.Response(
            404, json={"error": {"type": "not_found", "message": "No human request with that id."}}))
        link = nc.HumanRequestLink("hr_1", base_url=BASE)
        assert link.connect(credential_type="gmail_oauth") == "https://accounts.example.test/sign-in"
        assert json.loads(connected.calls.last.request.content) == {"credential_type": "gmail_oauth"}
        assert "k" not in connected.calls.last.request.url.params
        link.reply("I'll take it from here.")
        assert json.loads(replied.calls.last.request.content) == {"text": "I'll take it from here."}
        link.hand_back()
        assert back.call_count == 1
        with pytest.raises(nc.NotFound):
            nc.HumanRequestLink("hr_2", base_url=BASE).read()
