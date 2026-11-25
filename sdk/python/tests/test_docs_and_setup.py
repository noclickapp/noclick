"""The calls a coding agent makes before it has a key, and the one that hands an app's change to its coding agent:
the docs (searched and read with no key), a setup code redeemed for a key, and ``app.live.change``."""

import pytest

import noclick as nc
from platform_helpers import BASE, body, listing, operation


@pytest.fixture
def api_url(monkeypatch):
    monkeypatch.setenv("NOCLICK_API_URL", BASE)


def test_docs_are_searched_and_read_with_no_key(api, api_url):
    searched = api.get("/v1/docs").respond(json=listing(
        {"id": "guide:apps", "kind": "guide", "title": "Apps", "url": None, "snippet": "Deploy", "status": "built"}))
    read = api.get("/v1/docs/skill:ship-an-app").respond(json={
        "object": "doc", "id": "skill:ship-an-app", "kind": "skill", "title": "Ship an app", "summary": "s",
        "url": None, "status": "built", "text": "# Ship an app", "sections": []})
    [hit] = nc.Docs.search("deploy an app", limit=5)
    assert hit.id == "guide:apps"
    params = searched.calls.last.request.url.params
    assert (params["q"], params["limit"]) == ("deploy an app", "5")
    assert "authorization" not in searched.calls.last.request.headers
    assert nc.Docs.read("skill:ship-an-app").text == "# Ship an app"
    assert "authorization" not in read.calls.last.request.headers
    nc.Docs.search()  # a listing names no limit
    assert "limit" not in searched.calls.last.request.url.params


def test_a_setup_code_is_redeemed_for_a_key_with_no_key(api, api_url):
    redeemed = api.post("/v1/setup").respond(json={
        "object": "setup_key", "key": "nk_live_FAKESECRET0002", "key_id": "key_9", "key_name": "Coding agent",
        "key_prefix": "nk_live_FAKE", "email": "ana@acme.test"})
    key = nc.Key.redeem_setup_code("nc_setup_abc")
    request = redeemed.calls.last.request
    assert request.content == b"code=nc_setup_abc" and request.headers["accept"] == "application/json"
    assert "authorization" not in request.headers
    assert (key.id, key.name, key.secret, key.raw["email"]) == ("key_9", "Coding agent", "nk_live_FAKESECRET0002",
                                                                 "ana@acme.test")
    assert "key" not in key.raw and "FAKESECRET" not in repr(key)


def test_app_live_change_hands_the_change_to_its_coding_agent(api):
    api.get("/v1/projects").respond(json=listing({"object": "project", "id": "prj_1", "name": "larkspur"}))
    handed = api.post("/v1/projects/prj_1/live/changes").respond(202, json=operation(
        "op_c", kind="agent.message", status="running"))
    op = nc.Project.from_name("larkspur").live.change("Add a dark mode toggle", title="Dark mode")
    assert body(handed.calls.last.request) == {"text": "Add a dark mode toggle", "title": "Dark mode"}
    assert op.id == "op_c"
