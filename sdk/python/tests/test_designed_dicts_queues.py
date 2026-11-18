"""Dicts, queues and the OnQueue trigger (built; their exports designed): the routes, bodies
and parsed results the client sends and reads, against the mocked transport."""

import asyncio

import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID, agent_row, body, listing, operation, trashed

SEEN = {"object": "dict", "id": "dct_1", "name": "processed-orders", "key_count": 18240, "size_bytes": 2_411_520,
        "used_by": [{"kind": "project", "id": "prj_1", "name": "booking", "binding": "SEEN"}], "user_id": None,
        "created_at": "2026-09-25T10:00:00Z"}
JOBS = {"object": "queue", "id": "que_1", "name": "invoices", "depth": 14, "in_flight": 2, "dead_letter_count": 1,
        "max_attempts": 5, "used_by": [{"kind": "agent", "id": "ag_1", "name": "support-bot", "binding": None}],
        "user_id": None, "created_at": "2026-09-25T10:00:00Z"}


def _item(key, value, **extra):
    return {"object": "dict_item", "key": key, "value": value, "expires_at": None,
            "updated_at": "2026-09-26T09:00:00Z", "size_bytes": 24, **extra}


def _missing(key):
    return httpx.Response(404, json={"error": {"type": "not_found", "message": f"No key {key}.", "key": key}})


def _message(mid="msg_1", **extra):
    return {"object": "queue_message", "id": mid, "queue_id": "que_1", "body": {"invoice": "INV-1042"},
            "status": "in_flight", "attempts": 1, "enqueued_at": "2026-09-26T09:00:00Z", "visible_at": None,
            "lease_expires_at": "2026-09-26T09:02:00Z", "last_error": None, "dead_lettered_at": None,
            "lease_id": f"lease_{mid}", **extra}


# --- dicts: construction ------------------------------------------------------------

def test_dict_create_list_and_from_id(api, client):
    create = api.post("/v1/dicts").respond(json={**SEEN, "id": "dct_2", "name": "feature-flags", "user_id": USER_ID})
    listed = api.get("/v1/dicts").respond(json=listing(SEEN, next_cursor="c2"))
    api.get("/v1/dicts/dct_1").respond(json=SEEN)

    with nc.as_user("acme"):
        flags = nc.Dict.create("feature-flags")
    assert body(create.calls.last.request) == {"name": "feature-flags"}
    assert create.calls.last.request.headers["NoClick-User"] == "acme"
    assert repr(flags) == "Dict(id='dct_2', name='feature-flags')"

    page = nc.Dict.list_page(user_filter=nc.ALL_USERS, limit=10)
    params = listed.calls.last.request.url.params
    assert (params["user_id"], params["limit"]) == ("all", "10")
    assert "NoClick-User" not in listed.calls.last.request.headers
    assert page.next_cursor == "c2"
    [first] = nc.Dict.list(limit=1)
    assert (first.key_count, first.size_bytes, first.used_by[0]["binding"]) == (18240, 2_411_520, "SEEN")
    assert first.created_at.year == 2026
    loaded = nc.Dict.from_id("dct_1").hydrate()
    assert (loaded.name, loaded.console_url) == ("processed-orders", None)
    hosted = nc.Client(api_key="nk_live_test")
    assert nc.Dict.from_id("dct_1", client=hosted).console_url == f"{nc.CONSOLE_BASE_URL}/resources/dicts?dict=dct_1"
    assert bool(nc.Dict.from_name("anything"))  # truthiness never makes a call


def test_dict_from_name_finds_creates_adopts_or_says_how(api, client):
    lookup = api.get("/v1/dicts").mock(side_effect=[
        httpx.Response(200, json=listing({**SEEN, "name": "processed-orders-old"})),
        httpx.Response(200, json=listing()),
        httpx.Response(200, json=listing()),
    ])
    create = api.post("/v1/dicts").mock(side_effect=[
        httpx.Response(200, json={**SEEN, "id": "dct_9", "name": "cache"}),
        httpx.Response(409, json={"error": {"type": "conflict", "message": "taken", "existing_id": "dct_1"}}),
    ])
    api.get("/v1/dicts/dct_1").respond(json=SEEN)

    lazy = nc.Dict.from_name("cache", create_if_missing=True)
    assert lookup.call_count == 0 and lazy.name == "cache"
    assert lazy.id == "dct_9"  # an exact name only: the near miss isn't it
    assert lookup.calls[0].request.url.params["name"] == "cache"
    assert body(create.calls.last.request) == {"name": "cache"}
    with pytest.raises(nc.NotFound, match="create_if_missing=True"):
        nc.Dict.from_name("cache").hydrate()
    assert nc.Dict.from_name("processed-orders", create_if_missing=True).id == "dct_1"


# --- dicts: reading and writing keys ------------------------------------------------

def test_dict_protocol_reads_and_writes_keys(api, client):
    read = api.get("/v1/dicts/dct_1/items/o_1841").respond(json=_item("o_1841", {"status": "refunded"}))
    api.get("/v1/dicts/dct_1/items/o_1842").mock(return_value=_missing("o_1842"))
    write = api.put("/v1/dicts/dct_1/items/o_1843").respond(json={"object": "dict_item", "key": "o_1843", "written": True})
    delete = api.delete("/v1/dicts/dct_1/items/o_1841").respond(json=_item("o_1841", {"status": "refunded"}))
    api.delete("/v1/dicts/dct_1/items/o_1842").mock(return_value=_missing("o_1842"))
    api.get("/v1/dicts/dct_1").respond(json={**SEEN, "key_count": 3})
    seen = nc.Dict.from_id("dct_1", user=USER_ID)

    assert seen["o_1841"] == {"status": "refunded"}
    assert read.calls.last.request.headers["NoClick-User"] == USER_ID
    with pytest.raises(KeyError):
        seen["o_1842"]
    assert "o_1841" in seen and "o_1842" not in seen and 42 not in seen
    assert seen.get("o_1842") is None and seen.get("o_1842", default=0) == 0

    seen["o_1843"] = None  # JSON null is a value like any other
    assert body(write.calls.last.request) == {"value": None}
    seen.put("o_1843", {"status": "sent"}, ttl_s=86400)
    assert body(write.calls.last.request) == {"value": {"status": "sent"}, "ttl_s": 86400}
    with pytest.raises(TypeError, match="JSON"):
        seen.put("o_1843", {1, 2})
    with pytest.raises(TypeError, match="non-empty string"):
        seen.put("", 1)

    del seen["o_1841"]
    assert delete.call_count == 1
    with pytest.raises(KeyError):
        del seen["o_1842"]
    assert seen.remove("o_1841") is True and seen.remove("o_1842") is False
    assert seen.pop("o_1841") == {"status": "refunded"}
    assert seen.pop("o_1842", "gone") == "gone"
    with pytest.raises(KeyError):
        seen.pop("o_1842")
    assert len(seen) == 3 and seen.key_count == 3


def test_dict_a_missing_dict_is_not_a_missing_key(api, client):
    api.get("/v1/dicts/dct_404/items/a").respond(404, json={"error": {"type": "not_found", "message": "No such dict."}})
    with pytest.raises(nc.NotFound, match="No such dict"):
        nc.Dict.from_id("dct_404").get("a", default=1)


def test_dict_keys_are_escaped_in_the_path(api, client):
    read = api.get(path__startswith="/v1/dicts/dct_1/items/").respond(json=_item("lock:nightly/a b", 1))
    nc.Dict.from_id("dct_1").get("lock:nightly/a b")
    assert read.calls.last.request.url.raw_path == b"/v1/dicts/dct_1/items/lock%3Anightly%2Fa%20b"


def test_dict_put_if_absent_increment_and_update(api, client):
    put = api.put("/v1/dicts/dct_1/items/lock%3Anightly").mock(side_effect=[
        httpx.Response(200, json={"object": "dict_item", "key": "lock:nightly", "written": True}),
        httpx.Response(200, json={"object": "dict_item", "key": "lock:nightly", "written": False}),
    ])
    bump = api.post("/v1/dicts/dct_1/items/visits/increment").respond(json={"object": "dict_item", "key": "visits", "value": 42})
    many = api.post("/v1/dicts/dct_1/items").respond(json={"written": 2})
    seen = nc.Dict.from_id("dct_1")

    assert seen.put_if_absent("lock:nightly", "worker-3", ttl_s=300) is True
    assert body(put.calls.last.request) == {"value": "worker-3", "if_absent": True, "ttl_s": 300}
    assert seen.put_if_absent("lock:nightly", "worker-4") is False
    assert body(put.calls.last.request) == {"value": "worker-4", "if_absent": True}

    assert seen.increment("visits") == 42
    assert body(bump.calls.last.request) == {"by": 1}
    seen.increment("visits", by=-5, ttl_s=3600)
    assert body(bump.calls.last.request) == {"by": -5, "ttl_s": 3600}
    with pytest.raises(TypeError):
        seen.increment("visits", by=1.5)

    seen.update({"a": 1, "b": [2]}, ttl_s=60)
    assert body(many.calls.last.request) == {"items": [
        {"key": "a", "value": 1, "ttl_s": 60}, {"key": "b", "value": [2], "ttl_s": 60}]}
    seen.update({"c": None})
    assert body(many.calls.last.request) == {"items": [{"key": "c", "value": None}]}


def test_dict_keys_items_and_iteration_page_through(api, client):
    pages = api.get("/v1/dicts/dct_1/items").mock(side_effect=lambda request: httpx.Response(200, json=(
        listing(_item("o_1", 1, expires_at="2026-09-27T00:00:00Z"), _item("o_2", 2), next_cursor="c2")
        if "cursor" not in request.url.params else listing(_item("o_3", 3))
    )))
    seen = nc.Dict.from_id("dct_1")

    assert seen.keys(prefix="o_") == ["o_1", "o_2", "o_3"]
    first = pages.calls[0].request.url.params
    assert (first["prefix"], first["view"]) == ("o_", "keys")
    assert pages.calls[1].request.url.params["cursor"] == "c2"

    items = seen.items(limit=2)
    assert "view" not in pages.calls.last.request.url.params
    assert pages.calls.last.request.url.params["limit"] == "2"
    assert [(key, value) for key, value in items] == [("o_1", 1), ("o_2", 2)]
    assert dict(items) == {"o_1": 1, "o_2": 2}
    assert items[0].expires_at.day == 27 and items[1].expires_at is None and items[0].size_bytes == 24
    assert "value" not in repr(items[0])

    page = seen.items_page(prefix="o_", limit=2)
    assert page.next_cursor == "c2" and page.data[0].key == "o_1"
    count = api.get("/v1/dicts/dct_1").respond(json=SEEN)
    assert [key for key in seen] == ["o_1", "o_2", "o_3"] and count.call_count == 0


def test_dict_clear_export_and_delete(api, client):
    clear = api.post("/v1/dicts/dct_1/clear").respond(json={"removed": 18240, "operation_id": "op_clear"})
    export = api.post("/v1/dicts/dct_1/export").respond(json=operation(
        "op_9", kind="dict.export", status="succeeded",
        result={"url": "https://exports.example.com/processed-orders.zip", "expires_at": None, "contents": [],
                "remaining_dependencies": []}))
    delete = api.delete("/v1/dicts/dct_1").respond(409, json={"error": {
        "type": "conflict", "message": "The booking app binds processed-orders as SEEN.", "next_step": 'Unbind it first.'}})
    seen = nc.Dict.from_id("dct_1")

    assert seen.clear().id == "op_clear"
    assert clear.call_count == 1
    bundle = seen.export().wait()
    assert export.call_count == 1 and bundle.url.endswith("processed-orders.zip")
    with pytest.raises(nc.Conflict, match="binds"):
        seen.delete()
    assert delete.call_count == 1


def test_dict_async_forms(api, client):
    api.get("/v1/dicts/dct_1/items/a").respond(json=_item("a", 1))
    api.put("/v1/dicts/dct_1/items/b").respond(json={"key": "b", "written": True})

    async def main():
        seen = nc.Dict.from_id("dct_1")
        await seen.put.aio("b", 2)
        return await seen.get.aio("a")

    assert asyncio.run(main()) == 1


# --- queues -------------------------------------------------------------------------

def test_queue_create_list_and_from_name_converges_max_attempts(api, client):
    create = api.post("/v1/queues").respond(json={**JOBS, "id": "que_2", "name": "erp-exports", "max_attempts": 10})
    listed = api.get("/v1/queues").mock(side_effect=[
        httpx.Response(200, json=listing(JOBS, next_cursor="c2")),
        httpx.Response(200, json=listing(JOBS)),
        httpx.Response(200, json=listing(JOBS)),
        httpx.Response(200, json=listing()),
    ])
    patch = api.patch("/v1/queues/que_1").respond(json={**JOBS, "max_attempts": 8})

    with nc.as_user("acme"):
        exports = nc.Queue.create("erp-exports", max_attempts=10)
    assert body(create.calls.last.request) == {"name": "erp-exports", "max_attempts": 10}
    assert exports.max_attempts == 10
    nc.Queue.create("invoices")
    assert body(create.calls.last.request) == {"name": "invoices", "max_attempts": 5}

    page = nc.Queue.list_page(user_filter=nc.ALL_USERS)
    assert page.next_cursor == "c2" and page.data[0].used_by[0]["kind"] == "agent"
    assert (page.data[0].depth, page.data[0].in_flight, page.data[0].dead_letter_count) == (14, 2, 1)

    as_is = nc.Queue.from_name("invoices", create_if_missing=True)
    assert as_is.max_attempts == 5 and patch.call_count == 0  # nothing passed: left as it is
    changed = nc.Queue.from_name("invoices", create_if_missing=True, max_attempts=8)
    assert changed.max_attempts == 8 and body(patch.calls.last.request) == {"max_attempts": 8}
    nc.Queue.from_name("webhook-buffer", create_if_missing=True).hydrate()
    assert body(create.calls.last.request) == {"name": "webhook-buffer", "max_attempts": 5}
    assert listed.calls[-1].request.url.params["name"] == "webhook-buffer"


def test_queue_put_and_put_many(api, client):
    post = api.post("/v1/queues/que_1/messages").mock(side_effect=lambda request: httpx.Response(200, json=listing(
        *[{"object": "queue_message", "id": f"msg_{n}"} for n, _ in enumerate(body(request)["messages"], 1)])))
    jobs = nc.Queue.from_id("que_1", user=USER_ID)

    assert jobs.put({"invoice": "INV-1042"}) == "msg_1"
    assert body(post.calls.last.request) == {"messages": [{"body": {"invoice": "INV-1042"}}]}
    assert post.calls.last.request.headers["NoClick-User"] == USER_ID
    jobs.put({"check_payment": "INV-1042"}, delay_s=3600)
    assert body(post.calls.last.request) == {"messages": [{"body": {"check_payment": "INV-1042"}, "delay_s": 3600}]}
    assert jobs.put_many(["a", "b", "c"]) == ["msg_1", "msg_2", "msg_3"]
    assert body(post.calls.last.request) == {"messages": [{"body": "a"}, {"body": "b"}, {"body": "c"}]}


def test_queue_get_leases_and_the_message_acks_or_nacks(api, client):
    take = api.get("/v1/queues/que_1/messages").mock(side_effect=[
        httpx.Response(200, json=listing(_message())),
        httpx.Response(200, json=listing()),
    ])
    ack = api.post("/v1/queues/que_1/messages/msg_1/ack").respond(204)
    nack = api.post("/v1/queues/que_1/messages/msg_1/nack").respond(204)
    jobs = nc.Queue.from_id("que_1")

    msg = jobs.get(timeout_s=30, lease_s=120)
    params = take.calls.last.request.url.params
    assert (params["wait_s"], params["lease_s"], params["limit"]) == ("30", "120", "1")
    assert isinstance(msg, nc.QueueMessage)
    assert (msg.body, msg.attempts, msg.status, msg.queue_id) == ({"invoice": "INV-1042"}, 1, "in_flight", "que_1")
    assert msg.enqueued_at.hour == 9 and msg.lease_expires_at.minute == 2
    msg.ack()
    assert body(ack.calls.last.request) == {"lease_id": "lease_msg_1"}
    msg.nack(delay_s=60)
    assert body(nack.calls.last.request) == {"lease_id": "lease_msg_1", "delay_s": 60}
    msg.nack()
    assert body(nack.calls.last.request) == {"lease_id": "lease_msg_1"}

    assert jobs.get() is None
    assert "wait_s" not in take.calls.last.request.url.params


def test_queue_iterate_long_polls_until_you_stop(api, client):
    take = api.get("/v1/queues/que_1/messages").mock(side_effect=[
        httpx.Response(200, json=listing(_message("msg_1"))),
        httpx.Response(200, json=listing()),
        httpx.Response(200, json=listing(_message("msg_2"), _message("msg_3"))),
    ])
    jobs = nc.Queue.from_id("que_1")
    taken = []
    for msg in jobs.iterate(lease_s=90):
        taken.append(msg.id)
        if len(taken) == 3:
            break
    assert taken == ["msg_1", "msg_2", "msg_3"]
    assert {c.request.url.params["wait_s"] for c in take.calls} == {"25"}
    assert take.calls[0].request.url.params["lease_s"] == "90"
    assert len(client.sleeps) == 1  # the empty poll didn't spin

    async def first():
        async for msg in nc.Queue.from_id("que_1").iterate.aio():
            return msg.id

    take.side_effect = [httpx.Response(200, json=listing(_message("msg_4")))]
    assert asyncio.run(first()) == "msg_4"


def test_queue_peek_dead_letters_retry_and_discard(api, client):
    peek = api.get("/v1/queues/que_1/messages").respond(json=listing(
        _message("msg_5", status="waiting", lease_id=None, lease_expires_at=None)))
    dead = api.get("/v1/queues/que_1/dead_letters").respond(json=listing(_message(
        "msg_7", status="dead", attempts=5, lease_id=None, last_error="Stripe says the invoice doesn't exist.",
        dead_lettered_at="2026-09-26T08:00:00Z")))
    retry = api.post("/v1/queues/que_1/dead_letters/msg_7/retry").respond(204)
    discard = api.delete("/v1/queues/que_1/dead_letters/msg_7").respond(204)
    jobs = nc.Queue.from_id("que_1")

    [waiting] = jobs.peek(limit=5)
    params = peek.calls.last.request.url.params
    assert (params["view"], params["limit"]) == ("peek", "5")
    assert waiting.status == "waiting"
    with pytest.raises(nc.InvalidRequest, match="isn't leased"):
        waiting.ack()

    [letter] = jobs.dead_letters()
    assert (letter.attempts, letter.status, letter.dead_lettered_at.hour) == (5, "dead", 8)
    assert "doesn't exist" in letter.last_error
    assert dead.calls.last.request.url.path == "/v1/queues/que_1/dead_letters"
    letter.retry()
    letter.discard()
    assert (retry.call_count, discard.call_count) == (1, 1)


def test_queue_refresh_keeps_the_lease(api, client):
    api.get("/v1/queues/que_1/messages").respond(json=listing(_message()))
    api.get("/v1/queues/que_1/messages/msg_1").respond(json=_message(attempts=2, lease_id=None))
    ack = api.post("/v1/queues/que_1/messages/msg_1/ack").respond(204)
    msg = nc.Queue.from_id("que_1").get()
    msg.refresh()
    assert msg.attempts == 2
    msg.ack()
    assert body(ack.calls.last.request) == {"lease_id": "lease_msg_1"}


def test_queue_len_history_update_clear_export_and_delete(api, client):
    api.get("/v1/queues/que_1").respond(json={**JOBS, "depth": 16})
    history = api.get("/v1/queues/que_1/depth").respond(json=listing(
        {"at": "2026-09-26T08:00:00Z", "depth": 3, "in_flight": 1}, {"at": "2026-09-26T08:15:00Z", "depth": 16, "in_flight": 2}))
    patch = api.patch("/v1/queues/que_1").respond(json={**JOBS, "max_attempts": 10})
    clear = api.post("/v1/queues/que_1/clear").respond(json={"removed": 15})
    export = api.post("/v1/queues/que_1/export").respond(json=operation(
        "op_8", kind="queue.export", status="succeeded", result={"url": "https://exports.example.com/invoices.zip",
                                                                  "expires_at": None, "contents": [], "remaining_dependencies": []}))
    delete = api.delete("/v1/queues/que_1").respond(json=trashed("queue", "que_1", "invoices"))
    jobs = nc.Queue.from_id("que_1")

    assert jobs.len() == 16 and jobs.depth == 16
    points = jobs.depth_history(hours=6)
    assert history.calls.last.request.url.params["hours"] == "6"
    assert [(p.depth, p.in_flight) for p in points] == [(3, 1), (16, 2)] and points[1].at.minute == 15
    assert jobs.update(max_attempts=10).max_attempts == 10 and body(patch.calls.last.request) == {"max_attempts": 10}
    jobs.clear()
    assert jobs.export().wait().url.endswith("invoices.zip") and export.call_count == 1
    assert jobs.delete().name == "invoices"
    assert (clear.call_count, delete.call_count) == (1, 1)
    hosted = nc.Client(api_key="nk_live_test")
    assert nc.Queue.from_id("que_1", client=hosted).console_url == f"{nc.CONSOLE_BASE_URL}/resources/queues?queue=que_1"


# --- the OnQueue trigger -------------------------------------------------------------

def test_on_queue_wires_by_name_and_creates_a_lazy_queue_first(api, client):
    api.get("/v1/queues").respond(json=listing())
    create = api.post("/v1/queues").respond(json=JOBS)
    api.get("/v1/agents").respond(json=listing())
    agent_create = api.post("/v1/agents").respond(json=agent_row(name="support-bot"))

    invoices = nc.Queue.from_name("invoices", create_if_missing=True)
    nc.Agent.from_name(
        "support-bot", create_if_missing=True, instructions="You chase unpaid invoices.",
        triggers=[nc.OnQueue(invoices, message="Chase this unpaid invoice."), nc.OnQueue("webhook-buffer", batch_size=10)],
    ).hydrate()
    assert create.call_count == 1
    assert body(agent_create.calls.last.request)["triggers"] == [
        {"kind": "queue", "queue": "invoices", "batch_size": 1, "message": "Chase this unpaid invoice."},
        {"kind": "queue", "queue": "webhook-buffer", "batch_size": 10},
    ]
    assert repr(nc.OnQueue("webhook-buffer", batch_size=10)) == "OnQueue('webhook-buffer', batch_size=10)"
    with pytest.raises(TypeError, match="Queue or its name"):
        nc.OnQueue(42)
    with pytest.raises(ValueError, match="batch_size"):
        nc.OnQueue("invoices", batch_size=0)


def test_on_queue_triggers_converge_and_read_back(api, client):
    queue_trigger = {"object": "agent_trigger", "id": "tr_9", "kind": "queue",
                     "spec": {"queue": "invoices", "batch_size": 1, "message": None}, "status": "active", "url": None,
                     "next_run": None, "last_fired_at": "2026-09-26T09:00:00Z", "error": None,
                     "created_at": "2026-09-20T10:00:00Z"}
    api.get("/v1/agents").respond(json=listing(agent_row(name="support-bot")))
    api.get("/v1/agents/ag_1/triggers").respond(json=listing(queue_trigger))
    writes = [api.post("/v1/agents/ag_1/triggers"), api.delete(path__startswith="/v1/agents/ag_1/triggers/"),
              api.patch("/v1/agents/ag_1")]

    agent = nc.Agent.from_name("support-bot", create_if_missing=True, instructions="hi", triggers=[nc.OnQueue("invoices")])
    [trigger] = agent.triggers()
    assert all(w.call_count == 0 for w in writes)  # the same definition: nothing to change
    assert (trigger.kind, trigger.defined, trigger.spec["queue"], trigger.last_fired_at.hour) == ("queue", True, "invoices", 9)

    writes[1].respond(204)
    agent.remove_trigger(nc.OnQueue("invoices"))
    assert writes[1].calls.last.request.url.path == "/v1/agents/ag_1/triggers/tr_9"
