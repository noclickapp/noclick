import asyncio
import datetime

import httpx
import pytest

import noclick as nc
from noclick._sync import BoundMethod
from platform_helpers import BASE, USER_ID, body, listing, user_row

SESSION = {
    "object": "session", "id": "ses_1", "token": "nk_sess_secret123", "user_id": USER_ID,
    "scopes": ["agents", "humans"], "expires_at": "2026-09-25T11:00:00Z",
}


def test_every_round3_method_has_sync_and_aio_forms():
    inbox = nc.Inbox.from_id("inb_1")
    number = nc.PhoneNumber.from_id("pn_1")
    bound = [
        nc.Channel.list, nc.Inbox.create, nc.Inbox.get, nc.Inbox.list, nc.PhoneNumber.available,
        nc.PhoneNumber.buy, nc.PhoneNumber.get, nc.PhoneNumber.list, nc.User.from_id("t").session,
        inbox.delete, inbox.messages, inbox.message, inbox.stream, inbox.wait_for,
        number.release, number.answer_with, number.call, number.calls,
    ]
    for method in bound:
        assert isinstance(method, BoundMethod), method
        assert asyncio.iscoroutinefunction(method.aio) or method._is_gen, method


# --- sessions ---------------------------------------------------------------------

def test_user_session_mints_a_token_and_hides_it(api, client):
    lookup = api.get(f"/v1/users/{USER_ID}").respond(json=user_row())
    mint = api.post(f"/v1/users/{USER_ID}/sessions").respond(json=SESSION)
    session = nc.User.from_id(USER_ID).session(scopes=["agents", "humans"], ttl_s=3600)
    assert lookup.call_count == 0  # a known id needs no round trip
    assert body(mint.calls.last.request) == {"scopes": ["agents", "humans"], "ttl_s": 3600}
    assert "NoClick-User" not in mint.calls.last.request.headers  # user routes are account-level
    assert (session.id, session.token, session.user_id, session.scopes) == (
        "ses_1", "nk_sess_secret123", USER_ID, ["agents", "humans"])
    assert session.expires_at == datetime.datetime(2026, 9, 25, 11, tzinfo=datetime.timezone.utc)
    assert "nk_sess" not in repr(session) and "nk_sess" not in str(session)


def test_session_expiry_by_the_local_clock():
    now = datetime.datetime.now(datetime.timezone.utc)
    def at(when):
        return nc.Session(token="nk_sess_x", id="ses_1", user_id=USER_ID, scopes=[], expires_at=when, raw={})
    assert at(now - datetime.timedelta(seconds=5)).expired
    assert not at(now + datetime.timedelta(hours=1)).expired
    assert not at((now + datetime.timedelta(hours=1)).replace(tzinfo=None)).expired  # a naive time reads as UTC
    assert not at(None).expired


def test_session_from_your_id_with_a_single_scope_and_timedelta(api, client):
    mint = api.post("/v1/users/user_42/sessions").respond(json=SESSION)
    session = nc.User.from_id("user_42").session("inbox", ttl_s=datetime.timedelta(minutes=15))  # no GET first
    assert body(mint.calls.last.request) == {"scopes": ["inbox"], "ttl_s": 900}
    assert session.user_id == "user_42"
    nc.User.from_id(USER_ID).session(["agents"])
    assert body(mint.calls.last.request) == {"scopes": ["agents"]}


def test_session_for_a_lazy_user_with_create_if_missing_creates_it_first(api, client):
    api.get("/v1/users/user_42").respond(404, json={"error": {"type": "not_found", "message": "No such user."}})
    create = api.post("/v1/users").respond(json=user_row())
    mint = api.post("/v1/users/user_42/sessions").respond(json=SESSION)
    nc.User.from_id("user_42", create_if_missing=True).session(["agents"])
    assert create.call_count == 1 and mint.call_count == 1


def test_a_session_client_authenticates_with_the_token(api, client):
    api.post(f"/v1/users/{USER_ID}/sessions").respond(json=SESSION)
    agents = api.get("/v1/agents").respond(json=listing())
    session = nc.User.from_id(USER_ID).session(scopes=["agents"])

    for session_client in (session.client(), nc.Client.for_session(session), nc.Client.for_session(session.token,
                                                                                                    base_url=BASE),
                           nc.Client(api_key=session.token, base_url=BASE)):
        assert session_client.base_url == BASE
        nc.Agent.list(client=session_client)
        request = agents.calls.last.request
        assert request.headers["Authorization"] == "Bearer nk_sess_secret123"
        assert "NoClick-User" not in request.headers  # the token is pinned to its user


def test_for_session_refuses_a_secret_key():
    with pytest.raises(ValueError, match="nk_sess_"):
        nc.Client.for_session("nk_live_abc")


def test_a_session_outside_its_scopes_is_permission_denied(api, client):
    api.post("/v1/sandboxes").respond(403, json={"error": {
        "type": "permission_denied", "message": "This session can't use sandboxes.",
        "next_step": "Mint a session with the scope it needs."}})
    with pytest.raises(nc.PermissionDenied) as info:
        nc.Sandbox.create(client=nc.Client.for_session("nk_sess_x", base_url=BASE))
    assert info.value.next_step == "Mint a session with the scope it needs."


# --- agents: capability tools ------------------------------------------------------

def test_agents_take_search_fetch_and_code_tools(api, client):
    create = api.post("/v1/agents").respond(json={
        "object": "agent", "id": "agt_1", "name": "researcher", "tools": ["search", "fetch", "code", "gmail"],
    })
    agent = nc.Agent.create("researcher", instructions="Research.", tools=["search", "fetch", "code", "gmail"])
    assert body(create.calls.last.request)["tools"] == ["search", "fetch", "code", "gmail"]
    assert agent.tools == ["search", "fetch", "code", "gmail"]
    nc.Agent.create("r2", instructions="x", tools=nc.Toolkit(["search", "code"]))
    assert body(create.calls.last.request)["tools"] == ["search", "code"]


# --- channels -----------------------------------------------------------------------

CHANNEL = {
    "object": "channel", "id": "ch_1", "name": "launch", "mode": "mentions", "status": "open",
    "user_id": USER_ID, "created_at": "2026-09-25T10:00:00Z",
    "members": [{"id": "mem_1", "type": "a2a", "a2a_url": "https://remote.ai/a2a", "name": "remote",
                 "a2a_header_names": ["Authorization"]}],
}


def test_channel_list_filters_pages_and_limits(api, client):
    route = api.get("/v1/channels").mock(side_effect=[
        httpx.Response(200, json=listing(CHANNEL, {**CHANNEL, "id": "ch_2"}, next_cursor="c2")),
        httpx.Response(200, json=listing({**CHANNEL, "id": "ch_3"}, {**CHANNEL, "id": "ch_4"}, next_cursor="c3")),
    ])
    with nc.as_user("user_42"):
        channels = nc.Channel.list(status="open", limit=3)
    assert [c.id for c in channels] == ["ch_1", "ch_2", "ch_3"]
    first, second = (call.request.url.params for call in route.calls)
    assert (first["status"], first["limit"], "cursor" not in first) == ("open", "3", True)
    assert second["cursor"] == "c2"
    assert route.calls.last.request.headers["NoClick-User"] == "user_42"
    assert channels[0].members[0].a2a_header_names == ["Authorization"]
    assert channels[0].status == "open"  # rows arrive hydrated


def test_channel_list_follows_every_cursor_without_a_limit(api, client):
    route = api.get("/v1/channels").mock(side_effect=[
        httpx.Response(200, json=listing(CHANNEL, next_cursor="c2")),
        httpx.Response(200, json=listing({**CHANNEL, "id": "ch_2", "status": "closed"})),
    ])
    assert [c.id for c in nc.Channel.list()] == ["ch_1", "ch_2"]
    assert "limit" not in route.calls[0].request.url.params and "status" not in route.calls[0].request.url.params
    with pytest.raises(ValueError, match="status"):
        nc.Channel.list(status="archived")


def test_a2a_members_carry_headers(api, client):
    create = api.post("/v1/channels").respond(json=CHANNEL)
    add = api.post("/v1/channels/ch_1/members").respond(json={
        "id": "mem_2", "type": "a2a", "a2a_url": "https://b.ai/a2a", "a2a_header_names": ["X-Key"]})
    remote = nc.A2AMember("https://remote.ai/a2a", headers={"Authorization": "Bearer s3cret"}, name="remote")
    assert "s3cret" not in repr(remote)
    channel = nc.Channel.create("launch", members=[
        remote, {"a2a_url": "https://c.ai/a2a", "a2a_headers": {"X-Token": "t"}}, "https://d.ai/a2a",
    ])
    assert body(create.calls.last.request)["members"] == [
        {"a2a_url": "https://remote.ai/a2a", "a2a_headers": {"Authorization": "Bearer s3cret"}, "name": "remote"},
        {"a2a_url": "https://c.ai/a2a", "a2a_headers": {"X-Token": "t"}},
        {"a2a_url": "https://d.ai/a2a"},
    ]
    member = channel.add(nc.A2AMember("https://b.ai/a2a", headers={"X-Key": "k"}))
    assert body(add.calls.last.request) == {"a2a_url": "https://b.ai/a2a", "a2a_headers": {"X-Key": "k"}}
    assert member.a2a_header_names == ["X-Key"]


def test_remove_an_a2a_member_by_what_you_added(api, client):
    api.get("/v1/channels/ch_1").respond(json=CHANNEL)
    remove = api.delete("/v1/channels/ch_1/members/mem_1").respond(204)
    nc.Channel.from_id("ch_1").remove(nc.A2AMember("https://remote.ai/a2a", headers={"Authorization": "x"}))
    assert remove.call_count == 1


async def test_channel_list_aio(api, client):
    api.get("/v1/channels").respond(json=listing(CHANNEL))
    [channel] = await nc.Channel.list.aio(status="closed")
    assert channel.id == "ch_1"
