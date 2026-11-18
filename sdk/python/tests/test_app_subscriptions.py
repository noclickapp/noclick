"""An app's subscriptions against the mocked API: ``project.subscribe`` POSTs an ``OnEvent``'s events to a path,
``subscriptions``/``deliveries``/``test``/``unsubscribe`` read and drive them, ``connection.events()`` carries each
event's shape and sample, and ``agent.rehearse_trigger`` test-runs the turn a sample would start."""

import asyncio

import pytest

import noclick as nc
from platform_helpers import agent_row, body, listing, operation

SOURCE = {"kind": "event", "connection": "whatsapp", "event": "receive_message", "filters": {}}


def _subscription(**extra):
    return {"object": "subscription", "id": "sub_1", "channel_id": None, "workspace_id": None, "project_id": "prj_1",
            "path": "/hooks/whatsapp", "channels": None, "source": SOURCE, "wake": None, "filters": None,
            "status": "active", "error": None, "url": None, "last_event_at": None,
            "created_at": "2026-11-04T09:00:00Z", **extra}


def _delivery(**extra):
    return {"object": "subscription_delivery", "id": "dl_1", "subscription_id": "sub_1", "status": "delivered",
            "test": False, "attempts": 1, "response_status": 204, "response_body": None,
            "request_body": '{"object":"app_event"}', "duration_ms": 40, "error": None, "next_retry_at": None,
            "delivered_at": "2026-11-04T09:00:01Z", "created_at": "2026-11-04T09:00:00Z", **extra}


def test_every_call_has_sync_and_aio_forms():
    hook = nc.Subscription._new(raw=_subscription())
    for bound in (nc.Project.from_id("prj_1").subscribe, nc.Project.from_id("prj_1").subscriptions, hook.deliveries,
                  hook.test, nc.Agent.from_id("ag_1").rehearse_trigger):
        assert asyncio.iscoroutinefunction(bound.aio), bound


def test_an_app_subscribes_to_a_connections_events_at_one_of_its_paths(api, client):
    made = api.post("/v1/projects/prj_1/subscriptions").respond(json=_subscription())
    app = nc.Project.from_id("prj_1")
    hook = app.subscribe(nc.OnEvent("whatsapp", "receive_message"), path="/hooks/whatsapp")
    assert body(made.calls.last.request) == {"source": SOURCE, "path": "/hooks/whatsapp"}
    assert isinstance(hook, nc.Subscription)
    assert (hook.project_id, hook.path, hook.channel_id, hook.status) == ("prj_1", "/hooks/whatsapp", None, "active")
    with pytest.raises(TypeError, match="OnEvent"):
        app.subscribe(nc.OnWebhook(name="orders"), path="/hooks/orders")
    with pytest.raises(ValueError, match="message="):
        app.subscribe(nc.OnEvent("whatsapp", "receive_message", message="Answer it"), path="/hooks/whatsapp")
    assert len(api.calls) == 1


def test_an_apps_subscription_lists_what_it_sent_tests_and_stops(api, client):
    api.get("/v1/projects/prj_1/subscriptions").respond(json=listing(_subscription()))
    sent = api.get("/v1/projects/prj_1/subscriptions/sub_1/deliveries").respond(json=listing(
        _delivery(status="retrying", error="Answered 500", response_status=500, next_retry_at="2026-11-04T09:01:00Z")))
    tested = api.post("/v1/projects/prj_1/subscriptions/sub_1/test").respond(json=_delivery(id="dl_2", test=True))
    gone = api.delete("/v1/projects/prj_1/subscriptions/sub_1").respond(json={"id": "sub_1", "deleted": True})

    [hook] = nc.Project.from_id("prj_1").subscriptions()
    [retrying] = hook.deliveries(status=["retrying", "failed"])
    assert sent.calls.last.request.url.params["status"] == "retrying,failed"
    assert isinstance(retrying, nc.SubscriptionDelivery)
    assert (retrying.status, retrying.error, retrying.response_status) == ("retrying", "Answered 500", 500)
    assert retrying.next_retry_at is not None and retrying.request_body == '{"object":"app_event"}'
    sample = hook.test()
    assert tested.called and (sample.id, sample.test, sample.status) == ("dl_2", True, "delivered")
    hook.unsubscribe()
    assert gone.called
    # A channel's events are its messages: nothing to list or test.
    room = nc.Subscription._new(raw=_subscription(project_id=None, path=None, channel_id="ch_1"))
    with pytest.raises(TypeError, match="an app's"):
        room.test()


def test_an_events_shape_and_sample_come_with_the_catalog(api, client):
    shape = {"event": "string", "payload": {"from": "string", "body": "string", "hasMedia": "boolean"}}
    sample = {"event": "sample event", "payload": {"from": "sample from", "body": "sample body", "hasMedia": False}}
    api.get("/v1/integrations/whatsapp/events").respond(json=listing(
        {"object": "integration_event", "name": "receive_message", "description": "A message arrives",
         "filters": {}, "required_filters": [], "shape": shape, "sample": sample},
        {"object": "integration_event", "name": "unseen", "description": "Not seen yet", "filters": {},
         "required_filters": [], "shape": None, "sample": None},
    ))
    seen, unseen = nc.Connection.from_name("whatsapp", integration="whatsapp").events()
    assert (seen.shape, seen.sample) == (shape, sample)
    assert (unseen.shape, unseen.sample) == (None, None)


def test_rehearse_a_trigger_runs_the_turn_a_sample_of_its_event_starts(api, client):
    api.get("/v1/agents/ag_1").respond(json=agent_row(id="ag_1", name="inbox"))
    start = api.post("/v1/agents/ag_1/triggers/tr_5/test").respond(
        json=operation("op_r", "agent.rehearse", "running"))
    api.get("/v1/operations/op_r/wait").respond(json=operation(
        "op_r", "agent.rehearse", "succeeded", result={"reply": "Replied.", "tool_calls": [], "transcript": []}))
    op = nc.Agent.from_id("ag_1").rehearse_trigger("tr_5")
    assert start.called and isinstance(op.wait(), nc.Rehearsal)
