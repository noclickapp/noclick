import asyncio
import threading

import httpx
import pytest

import noclick as nc
from noclick._sync import BoundMethod, run_sync, synced
from platform_helpers import USER_ID, body, listing, operation, user_row


# --- sync / .aio parity ----------------------------------------------------

def test_every_public_method_has_sync_and_aio_forms():
    methods = {
        nc.User: ["create", "get", "list"],
        nc.Connection: ["create", "get", "list", "list_page", "integrations"],
        nc.Agent: ["create", "get", "list"],
        nc.Connection.from_name("gmail"): ["connect_link", "request", "wait", "import_", "run", "lookup", "verify",
                                           "token", "delete", "operations", "operation", "events"],
    }
    for owner, names in methods.items():
        for name in names:
            bound = getattr(owner, name)
            assert isinstance(bound, BoundMethod), (owner, name)
            assert asyncio.iscoroutinefunction(bound.aio), (owner, name)


def test_sync_and_aio_return_the_same_thing(api, client):
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row())
    sync_user = nc.User.get(USER_ID)
    aio_user = asyncio.run(nc.User.get.aio(USER_ID))
    assert type(sync_user) is type(aio_user) is nc.User
    assert sync_user == aio_user and sync_user.raw == aio_user.raw


async def test_aio_runs_on_the_callers_loop(api, client):
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row())
    user = await nc.User.get.aio(USER_ID)
    assert (user.id, user.status) == (USER_ID, "active")


async def test_blocking_call_works_inside_a_running_loop(api, client):
    # Jupyter: a loop is already running in this thread.
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row())
    assert nc.User.get(USER_ID).id == USER_ID


def test_blocking_call_from_sdk_loop_is_refused():
    class Probe:
        @synced
        async def inner(self):
            return 1

        @synced
        async def outer(self):
            return self.inner()  # blocking form from inside the loop

    with pytest.raises(RuntimeError, match=r"\.aio"):
        Probe().outer()


def test_async_generator_methods_iterate_both_ways(api, client):
    api.get("/v1/operations/op_1").mock(side_effect=[
        httpx.Response(200, json=operation(status="queued")),
        httpx.Response(200, json=operation(status="running")),
        httpx.Response(200, json=operation(status="running")),
        httpx.Response(200, json=operation(status="succeeded", result={"answer": "yes"})),
    ] * 2)
    op = nc.Operation.from_id("op_1")
    assert [e.status for e in op.events(interval=0)] == ["queued", "running", "succeeded"]

    async def collect():
        return [e.status async for e in nc.Operation.from_id("op_1").events.aio(interval=0)]

    assert asyncio.run(collect()) == ["queued", "running", "succeeded"]


def test_events_carry_a_cli_turns_step(api, client):
    api.get("/v1/operations/op_1").mock(side_effect=[
        httpx.Response(200, json=operation(status="running", step="delivering")),
        httpx.Response(200, json=operation(status="running", step="working")),
        httpx.Response(200, json=operation(status="succeeded", result={})),
    ])
    events = list(nc.Operation.from_id("op_1").events(interval=0))
    assert [(e.status, e.step) for e in events] == [("running", "delivering"), ("running", "working"), ("succeeded", None)]


def test_errors_raise_through_the_blocking_form(api, client):
    api.get("/v1/users/x").respond(404, json={"error": {"type": "not_found", "message": "no"}})
    with pytest.raises(nc.NotFound):
        nc.User.get("x")


def test_run_sync_from_many_threads():
    async def square(n):
        await asyncio.sleep(0)
        return n * n

    results = {}

    def work(n):
        results[n] = run_sync(square(n))

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == {n: n * n for n in range(8)}


# --- acting for a user ------------------------------------------------------

def _user_header(route):
    return route.calls.last.request.headers.get("NoClick-User")


def test_no_user_header_by_default(api, client):
    route = api.get("/v1/connections").respond(json=listing())
    nc.Connection.list()
    assert _user_header(route) is None


def test_as_user_sends_your_id_as_is(api, client):
    route = api.get("/v1/connections").respond(json=listing())
    for user_id in ("user_42", "5f0c9a1e-8b7d-4c3a-9e21-6d4f2b8a1c73", "auth0|6f1c2b7e9a"):
        with nc.as_user(user_id):
            nc.Connection.list()
        assert _user_header(route) == user_id


def test_as_user_nests_and_restores(api, client):
    route = api.get("/v1/connections").respond(json=listing())
    with nc.as_user("a"):
        with nc.as_user("b"):
            nc.Connection.list()
            assert _user_header(route) == "b"
        nc.Connection.list()
        assert _user_header(route) == "a"
        with nc.as_user(None):
            nc.Connection.list()
            assert _user_header(route) is None
    assert nc.current_user() is None


def test_explicit_user_argument_wins(api, client):
    route = api.get("/v1/connections").respond(json=listing())
    with nc.as_user("a"):
        nc.Connection.list(user="b")
        assert _user_header(route) == "b"
        nc.Connection.list(user=None)
        assert _user_header(route) is None


async def test_as_user_in_async_code(api, client):
    route = api.get("/v1/connections").respond(json=listing())
    async with nc.as_user("user_7"):
        await nc.Connection.list.aio()
        assert _user_header(route) == "user_7"
        nc.Connection.list()  # the blocking form carries the context too
        assert _user_header(route) == "user_7"


def test_as_user_with_hydrated_user(api, client):
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row())
    route = api.get("/v1/connections").respond(json=listing())
    user = nc.User.get(USER_ID)
    with nc.as_user(user):
        nc.Connection.list()
    assert _user_header(route) == USER_ID


def test_lazy_user_without_create_sends_its_id_and_no_lookup(api, client):
    lookup = api.get("/v1/users/user_42").respond(json=user_row())
    route = api.get("/v1/connections").respond(json=listing())
    with nc.as_user(nc.User.from_id("user_42")):
        nc.Connection.list()
    assert _user_header(route) == "user_42"
    assert lookup.call_count == 0


def test_lazy_user_with_create_if_missing_is_created_before_use(api, client):
    lookup = api.get("/v1/users/user_42").respond(404, json={"error": {"type": "not_found", "message": "No user."}})
    create = api.post("/v1/users").respond(json=user_row(email="ana@example.com"))
    route = api.get("/v1/connections").respond(json=listing())
    user = nc.User.from_id("user_42", create_if_missing=True, email="ana@example.com")
    assert not user.is_hydrated and create.call_count == 0  # lazy
    with nc.as_user(user):
        nc.Connection.list()
        nc.Connection.list()
    assert _user_header(route) == "user_42"
    assert lookup.call_count == 1 and create.call_count == 1
    assert body(create.calls.last.request) == {"id": "user_42", "email": "ana@example.com"}
    # user routes never carry a user header
    assert "NoClick-User" not in create.calls.last.request.headers


def test_as_user_rejects_other_types():
    with pytest.raises(TypeError):
        nc.as_user(42)
