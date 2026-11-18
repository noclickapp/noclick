"""Parity with the TypeScript client (test/console.test.ts): the token provider,
the page primitive and read-side user filters."""

import asyncio

import httpx
import pytest

import noclick as nc
from platform_helpers import BASE, USER_ID, agent_row, listing, user_row

AGENT = agent_row()


async def _no_sleep(_delay):
    return None


# --- token provider ------------------------------------------------------------


def test_an_async_api_key_function_is_asked_on_every_attempt(api):
    route = api.get("/v1/users")
    route.side_effect = [
        httpx.Response(503, json={"error": {"type": "server_error", "message": "busy"}}),
        httpx.Response(200, json=listing(user_row())),
    ]
    issued = []

    async def provider():
        issued.append(f"jwt_{len(issued) + 1}")
        return issued[-1]

    client = nc.Client(api_key=provider, base_url=BASE, max_retries=1)
    client._sleep = _no_sleep
    nc.User.list(client=client)
    assert issued == ["jwt_1", "jwt_2"]
    assert [c.request.headers["authorization"] for c in route.calls] == ["Bearer jwt_1", "Bearer jwt_2"]


def test_a_sync_provider_works_and_an_empty_one_is_unauthenticated(api):
    route = api.get("/v1/brand").respond(json={"object": "brand", "name": "Acme"})
    nc.Brand.get(client=nc.Client(api_key=lambda: "jwt_sync", base_url=BASE))
    assert route.calls.last.request.headers["authorization"] == "Bearer jwt_sync"
    with pytest.raises(nc.Unauthenticated):
        nc.Brand.get(client=nc.Client(api_key=lambda: "", base_url=BASE))
    assert route.call_count == 1


def test_a_provider_that_never_returns_is_cut_off_by_the_timeout(api):
    route = api.get("/v1/brand").respond(json={"object": "brand"})

    async def stuck():
        await asyncio.Event().wait()

    client = nc.Client(api_key=stuck, base_url=BASE, timeout=0.05, max_retries=0)
    with pytest.raises(nc.Unauthenticated, match="did not return a key within 0.05s"):
        nc.Brand.get(client=client)
    assert route.call_count == 0


def test_a_static_key_is_still_sent_as_is(api, client):
    route = api.get("/v1/brand").respond(json={"object": "brand"})
    nc.Brand.get()
    assert route.calls.last.request.headers["authorization"] == "Bearer nk_live_test"


# --- pages ----------------------------------------------------------------------


def test_list_page_returns_one_page_and_list_still_drains(api, client):
    route = api.get("/v1/users")
    route.side_effect = [
        httpx.Response(200, json=listing(user_row("a"), next_cursor="c2")),
        httpx.Response(200, json=listing(user_row("b"))),
    ]
    page = nc.User.list_page(limit=1, q="ac", status="suspended")
    assert [u.id for u in page.data] == ["a"] and page.next_cursor == "c2"
    params = route.calls.last.request.url.params
    assert (params["limit"], params["q"], params["status"]) == ("1", "ac", "suspended")
    assert "cursor" not in params

    following = nc.User.list_page(cursor=page.next_cursor)
    assert [u.id for u in following.data] == ["b"] and following.next_cursor is None
    assert route.calls.last.request.url.params["cursor"] == "c2"

    route.side_effect = [
        httpx.Response(200, json=listing(user_row("a"), next_cursor="c2")),
        httpx.Response(200, json=listing(user_row("b"))),
    ]
    assert [u.id for u in nc.User.list()] == ["a", "b"]
    assert route.call_count == 4


# --- user filters -------------------------------------------------------------------


def test_user_filter_sends_user_id_and_never_the_header(api, client):
    route = api.get("/v1/agents").respond(json=listing(AGENT))
    with nc.as_user("user_42"):
        nc.Agent.list_page(user_filter=nc.ALL_USERS)
    request = route.calls.last.request
    assert request.url.params["user_id"] == "all" and "NoClick-User" not in request.headers

    cases = [
        (nc.NO_USER, "none"),
        ("acme", "acme"),
        (USER_ID, USER_ID),
        (nc.User.from_id(USER_ID), USER_ID),
        (nc.User.from_id("acme"), "acme"),
    ]
    for value, sent in cases:
        nc.Agent.list(user_filter=value)
        assert route.calls.last.request.url.params["user_id"] == sent


def test_the_user_argument_is_still_the_header(api, client):
    route = api.get("/v1/agents").respond(json=listing(AGENT))
    nc.Agent.list(user="acme")
    request = route.calls.last.request
    assert request.headers["NoClick-User"] == "acme" and "user_id" not in request.url.params
    with pytest.raises(nc.InvalidRequest, match="reserved"):
        nc.Agent.list(user=nc.ALL_USERS)  # a filter value, never a user to act for
    with pytest.raises(TypeError, match="not both"):
        nc.Agent.list(user="acme", user_filter=nc.ALL_USERS)
    assert route.call_count == 1


def test_rows_from_a_filtered_read_act_for_their_own_user(api, client):
    api.get("/v1/sandboxes").respond(json=listing(
        {"object": "sandbox", "id": "sb_1", "status": "running", "user_id": USER_ID},
        {"object": "sandbox", "id": "sb_2", "status": "running", "user_id": None},
    ))
    exec1 = api.post("/v1/sandboxes/sb_1/exec").respond(json={"stdout": "", "stderr": "", "exit_code": 0})
    exec2 = api.post("/v1/sandboxes/sb_2/exec").respond(json={"stdout": "", "stderr": "", "exit_code": 0})
    owned, account = nc.Sandbox.list(user_filter=nc.ALL_USERS)
    owned.exec("true")
    account.exec("true")
    assert exec1.calls.last.request.headers["NoClick-User"] == USER_ID
    assert "NoClick-User" not in exec2.calls.last.request.headers


@pytest.mark.parametrize("path, call", [
    ("/v1/connections", lambda: nc.Connection.list_page(user_filter="acme", limit=5)),
    ("/v1/channels", lambda: nc.Channel.list_page(user_filter="acme", limit=5, status="open")),
    ("/v1/sandboxes", lambda: nc.Sandbox.list_page(user_filter="acme", limit=5, status="live")),
    ("/v1/inboxes", lambda: nc.Inbox.list_page(user_filter="acme", limit=5)),
    ("/v1/phone_numbers", lambda: nc.PhoneNumber.list_page(user_filter="acme", limit=5)),
])
def test_every_owned_resource_pages_with_a_user_filter(api, client, path, call):
    route = api.get(path).respond(json=listing({"id": "x_1", "user_id": USER_ID}, next_cursor="next"))
    page = call()
    assert len(page.data) == 1 and page.next_cursor == "next"
    request = route.calls.last.request
    assert request.url.params["user_id"] == "acme" and request.url.params["limit"] == "5"
    assert "NoClick-User" not in request.headers


def test_sandbox_list_filters_by_status(api, client):
    route = api.get("/v1/sandboxes").respond(json=listing())
    nc.Sandbox.list(status="live")
    assert route.calls.last.request.url.params["status"] == "live"


def test_a_naive_datetime_is_refused(api, client):
    import datetime

    with pytest.raises(ValueError, match="timezone-aware"):
        nc.Operation.list_page(created_after=datetime.datetime(2026, 9, 25))
