import datetime

import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID, body, listing, operation, user_row


# --- User ------------------------------------------------------------------

def test_create_sends_your_id_and_reads_the_fields(api, client):
    route = api.post("/v1/users").respond(json=user_row(name="Ana", metadata={"plan": "pro"}))
    user = nc.User.create("user_42", name="Ana", metadata={"plan": "pro"})
    assert body(route.calls.last.request) == {"id": "user_42", "name": "Ana", "metadata": {"plan": "pro"}}
    assert "NoClick-User" not in route.calls.last.request.headers  # user routes are account-level
    assert (user.id, user.name, user.metadata) == ("user_42", "Ana", {"plan": "pro"})
    assert user.created_at == datetime.datetime(2026, 9, 25, 10, tzinfo=datetime.timezone.utc)
    assert user.raw["object"] == "user"
    assert repr(user) == "User(id='user_42', status='active')"


def test_create_with_a_taken_id_raises_conflict_naming_it(api, client):
    api.post("/v1/users").respond(
        409, json={"error": {"type": "conflict", "message": "Taken.", "existing_id": "user_42"}},
    )
    with pytest.raises(nc.Conflict) as info:
        nc.User.create("user_42")
    assert info.value.existing_id == "user_42"


def test_from_id_is_lazy_and_loads_by_your_id(api, client):
    get = api.get(f"/v1/users/{USER_ID}").respond(json=user_row(email="ana@example.com"))
    create = api.post("/v1/users").respond(json=user_row())
    user = nc.User.from_id("user_42", create_if_missing=True)
    assert user.id == "user_42" and not user.is_hydrated and get.call_count == 0  # known locally
    assert user.email == "ana@example.com" and get.call_count == 1  # hydrates
    assert create.call_count == 0


def test_from_id_converges_an_existing_user_to_the_definition(api, client):
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row(name="Ana", email="old@example.com", phone="+14155550100"))
    create = api.post("/v1/users").respond(json=user_row())
    patch = api.patch(f"/v1/users/{USER_ID}").mock(
        side_effect=lambda request: httpx.Response(200, json=user_row(name="Ana", **body(request))))
    user = nc.User.from_id("user_42", create_if_missing=True, name="Ana", email="ana@example.com", phone=None,
                           metadata={"plan": "pro"})
    assert user.email == "ana@example.com" and create.call_count == 0
    # Only what differs is sent; None clears; a field left out (the spend cap) is never touched.
    assert body(patch.calls.last.request) == {"email": "ana@example.com", "phone": None, "metadata": {"plan": "pro"}}
    nc.User.from_id("user_42", create_if_missing=True, name="Ana").hydrate()
    assert patch.call_count == 1
    # Creating sends only the fields given, never a None.
    api.get("/v1/users/user_7").respond(404, json={"error": {"type": "not_found", "message": "No user."}})
    new = api.post("/v1/users").respond(json=user_row("user_7"))
    nc.User.from_id("user_7", create_if_missing=True, email="bo@example.com", phone=None).hydrate()
    assert body(new.calls.last.request) == {"id": "user_7", "email": "bo@example.com"}


@pytest.mark.parametrize("user_id,segment", [
    ("auth0|123", b"auth0%7C123"), ("a%2Fb", b"a%252Fb"), ("?#", b"%3F%23"), ("...", b"..."),
])
def test_ids_are_percent_encoded_in_paths(api, client, user_id, segment):
    route = api.route(method="GET", path__startswith="/v1/users/").respond(json=user_row(user_id))
    suspend = api.route(method="POST", path__startswith="/v1/users/").respond(json=user_row(user_id, status="suspended"))
    assert nc.User.get(user_id).suspend().id == user_id
    assert route.calls.last.request.url.raw_path == b"/v1/users/" + segment
    assert suspend.calls.last.request.url.raw_path == b"/v1/users/" + segment + b"/suspend"


def test_from_id_missing_without_create_raises_the_servers_not_found(api, client):
    api.get("/v1/users/ghost").respond(404, json={"error": {"type": "not_found", "message": "No user 'ghost'."}})
    create = api.post("/v1/users").respond(json=user_row("ghost"))
    with pytest.raises(nc.NotFound) as info:
        nc.User.from_id("ghost").hydrate()
    assert info.value.message == "No user 'ghost'." and create.call_count == 0


def test_from_id_create_race_adopts_existing(api, client):
    api.get(f"/v1/users/{USER_ID}").mock(side_effect=[
        httpx.Response(404, json={"error": {"type": "not_found", "message": "No such user."}}),
        httpx.Response(200, json=user_row(name="Ana")),
    ])
    create = api.post("/v1/users").respond(
        409, json={"error": {"type": "conflict", "message": "dup", "existing_id": USER_ID}},
    )
    user = nc.User.from_id("user_42", create_if_missing=True).hydrate()
    assert user.name == "Ana" and create.call_count == 1


def test_update_suspend_delete(api, client):
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row())
    patch = api.patch(f"/v1/users/{USER_ID}").respond(json=user_row(name="Ana", phone=None))
    api.post(f"/v1/users/{USER_ID}/suspend").respond(json=user_row(status="suspended"))
    delete = api.delete(f"/v1/users/{USER_ID}").respond(json=user_row(status="deleted"))
    user = nc.User.from_id(USER_ID)
    assert user.update(name="Ana", phone=None) is user
    assert body(patch.calls.last.request) == {"name": "Ana", "phone": None}
    assert user.name == "Ana"
    assert user.suspend().status == "suspended"
    user.delete()
    assert user.status == "deleted" and delete.call_count == 1


def test_update_sends_the_change_without_reading_the_user_first(api, client):
    """A user's own session may move its timezone but can't read the user, so update() only PATCHes."""
    read = api.get(f"/v1/users/{USER_ID}").respond(403, json={"error": {
        "type": "permission_denied", "message": "This user session lacks the 'users' scope."}})
    patch = api.patch(f"/v1/users/{USER_ID}").respond(json=user_row(timezone="Asia/Tokyo"))
    user = nc.User.from_id(USER_ID)
    assert user.update(timezone="Asia/Tokyo").timezone == "Asia/Tokyo"
    assert read.call_count == 0 and body(patch.calls.last.request) == {"timezone": "Asia/Tokyo"}


def test_update_id_moves_the_user_to_the_new_id(api, client):
    api.get("/v1/users/user_42").respond(json=user_row())
    patch = api.patch("/v1/users/user_42").respond(json=user_row("acct_9f3a"))
    renamed = api.get("/v1/users/acct_9f3a").respond(json=user_row("acct_9f3a", name="Ana"))
    connections = api.get("/v1/connections").respond(json=listing())
    user = nc.User.from_id("user_42")
    assert user.update(id="acct_9f3a") is user
    assert body(patch.calls.last.request) == {"id": "acct_9f3a"}
    assert user.id == "acct_9f3a"
    assert user.refresh().name == "Ana" and renamed.call_count == 1  # later calls use the new id
    with nc.as_user(user):
        nc.Connection.list()
    assert connections.calls.last.request.headers["NoClick-User"] == "acct_9f3a"


def test_update_to_a_taken_id_raises_conflict(api, client):
    api.get("/v1/users/user_42").respond(json=user_row())
    api.patch("/v1/users/user_42").respond(
        409, json={"error": {"type": "conflict", "message": "Taken.", "existing_id": "globex"}},
    )
    user = nc.User.from_id("user_42")
    with pytest.raises(nc.Conflict) as info:
        user.update(id="globex")
    assert info.value.existing_id == "globex" and user.id == "user_42"


def test_list_with_filter(api, client):
    route = api.get("/v1/users").respond(json=listing(user_row()))
    [user] = nc.User.list(q="ana", status="active")
    params = route.calls.last.request.url.params
    assert user.id == USER_ID and (params["q"], params["status"]) == ("ana", "active")
    assert "user_id" not in params and "NoClick-User" not in route.calls.last.request.headers


# --- user ids --------------------------------------------------------------

@pytest.mark.parametrize("bad,rule", [
    ("", "1 to 255 characters"),
    ("x" * 256, "1 to 255 characters"),
    ("ana lima", "printable ASCII"),
    ("ana\tlima", "printable ASCII"),
    ("jos\u00e9", "printable ASCII"),
    ("org/42", "'/'"),
    ("all", "reserved"),
    ("none", "reserved"),
    (".", "resolve it away"),
    ("..", "resolve it away"),
])
def test_an_invalid_id_raises_invalid_request_naming_the_rule_and_sends_nothing(api, client, bad, rule):
    sent = api.route().respond(json=user_row())
    attempts = [
        lambda: nc.User.create(bad),
        lambda: nc.User.from_id(bad),
        lambda: nc.User.get(bad),
        lambda: nc.User.from_id("user_42").update(id=bad),
        lambda: nc.as_user(bad),
        lambda: nc.Connection.list(user=bad),
    ]
    if bad not in (nc.ALL_USERS, nc.NO_USER):
        attempts.append(lambda: nc.Connection.list(user_filter=bad))
    for attempt in attempts:
        with pytest.raises(nc.InvalidRequest) as info:
            attempt()
        assert rule in info.value.message and info.value.next_step
    assert sent.call_count == 0


@pytest.mark.parametrize("good", ["a", "x" * 255, "!~", "auth0|6f1c2b7e9a", "5f0c9a1e-8b7d-4c3a-9e21-6d4f2b8a1c73"])
def test_any_valid_id_is_your_id_sent_as_is(api, client, good):
    route = api.get("/v1/connections").respond(json=listing())
    with nc.as_user(good):
        nc.Connection.list()
    assert route.calls.last.request.headers["NoClick-User"] == good  # no prefix, no UUID sniffing
    nc.Connection.list(user_filter=good)
    assert route.calls.last.request.url.params["user_id"] == good


def test_the_id_rule_names_the_id_field(api, client):
    for attempt in (lambda: nc.User.create("ana lima"), lambda: nc.as_user("ana lima"),
                    lambda: nc.Agent.list(user="ana lima"), lambda: nc.Agent.list(user_filter="ana lima")):
        with pytest.raises(nc.InvalidRequest) as info:
            attempt()
        assert info.value.field == "id"


def test_a_user_id_must_be_a_string():
    with pytest.raises(TypeError):
        nc.User.from_id(42)


# --- Operation ---------------------------------------------------------------

def test_wait_long_polls_until_terminal(api, client):
    route = api.get("/v1/operations/op_1/wait").mock(side_effect=[
        httpx.Response(200, json=operation(status="awaiting_human")),
        httpx.Response(200, json=operation(status="succeeded", result={"choice": "Tuesday", "text": None})),
    ])
    answer = nc.Operation.from_id("op_1").wait()
    assert isinstance(answer, nc.Answer) and answer.choice == "Tuesday" and str(answer) == "Tuesday"
    assert route.call_count == 2
    assert route.calls.last.request.url.params["timeout_s"] == "50"


def test_wait_rides_out_a_long_poll_cut_off_by_a_stopping_server(api, client):
    """A server stopping cuts its long-polls off: the caller gets the platform's 500 or a dropped
    connection, and asks again."""
    route = api.get("/v1/operations/op_1/wait").mock(side_effect=[
        httpx.Response(500, text="Internal Server Error"),
        httpx.ReadError("Server disconnected without sending a response."),
        httpx.Response(200, json=operation(status="succeeded", result={"choice": "Tuesday", "text": None})),
    ])
    assert nc.Operation.from_id("op_1").wait().choice == "Tuesday"
    assert route.call_count == 3 and len(client.sleeps) == 2


def test_wait_returns_immediately_when_already_done(api, client):
    route = api.get("/v1/operations/op_1/wait").respond(json=operation())
    op = nc.Operation._from_payload(operation(kind="human.notify", status="succeeded", result={}), client=None, user=None)
    assert op.wait() is None and route.call_count == 0


def test_wait_timeout(api, client):
    api.get("/v1/operations/op_1/wait").respond(json=operation(status="awaiting_human"))
    with pytest.raises(nc.OperationTimeout) as info:
        nc.Operation.from_id("op_1").wait(timeout=0.01)
    assert isinstance(info.value, TimeoutError) and info.value.operation_status == "awaiting_human"


def test_wait_raises_the_operation_error(api, client):
    api.get("/v1/operations/op_1/wait").respond(json=operation(status="failed", error={
        "type": "payment_required", "message": "Your account can't pay for this: $0.12 left, $0.50 needed.",
        "next_step": "Add funds.", "balance_usd": 0.12, "required_usd": 0.5,
    }))
    op = nc.Operation.from_id("op_1")
    with pytest.raises(nc.PaymentRequired) as info:
        op.wait()
    assert info.value.operation_id == "op_1"
    assert (info.value.balance_usd, info.value.required_usd) == (0.12, 0.5)
    assert isinstance(op.error, nc.PaymentRequired) and op.done


@pytest.mark.parametrize("status,cls", [("expired", nc.OperationExpired), ("canceled", nc.OperationCanceled),
                                        ("failed", nc.OperationFailed)])
def test_wait_terminal_without_error_details(api, client, status, cls):
    api.get("/v1/operations/op_1/wait").respond(json=operation(status=status))
    with pytest.raises(cls):
        nc.Operation.from_id("op_1").wait()


def test_unknown_kind_returns_raw_result(api, client):
    api.get("/v1/operations/op_1/wait").respond(json=operation(kind="future.kind", status="succeeded", result={"x": 1}))
    assert nc.Operation.from_id("op_1").wait() == {"x": 1}


def test_status_fields_and_cancel(api, client):
    api.get("/v1/operations/op_1").respond(json=operation(status="running"))
    cancel = api.post("/v1/operations/op_1/cancel").respond(json=operation(status="canceled"))
    op = nc.Operation.from_id("op_1")
    assert (op.status, op.kind, op.done, op.error) == ("running", "human.ask", False, None)
    assert op.cancel().status == "canceled"
    assert "Idempotency-Key" in cancel.calls.last.request.headers


async def test_wait_aio(api, client):
    api.get("/v1/operations/op_1/wait").respond(json=operation(kind="human.approve", status="succeeded",
                                                                result={"approved": True}))
    assert await nc.Operation.from_id("op_1").wait.aio() is True
