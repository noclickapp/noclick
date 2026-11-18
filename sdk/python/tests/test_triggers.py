"""Triggers, channel subscriptions and the events catalog against the mocked API:
``OnWebhook`` and ``OnEvent`` on an agent (create, convergence from a definition,
``triggers``/``add_trigger``/``remove_trigger``), ``channel.subscribe`` /
``subscriptions`` / ``unsubscribe``, an app's posts in a room, and
``connection.events()``."""

import asyncio

import pytest

import noclick as nc
from platform_helpers import USER_ID, agent_row, body, listing

AGENT = agent_row(id="ag_1", name="support")


def _trigger(trigger_id, kind, spec, **extra):
    return {"object": "agent_trigger", "id": trigger_id, "agent_id": "ag_1", "kind": kind, "spec": spec,
            "status": "active", "url": None, "next_run": None, "last_fired_at": None, "error": None,
            "created_at": "2026-10-01T10:00:00Z", **extra}


WEBHOOK = _trigger("tr_2", "webhook", {"name": "orders"}, url="https://wh_1.example.com")
EVENT = _trigger("tr_5", "event", {"connection": "slack", "event": "channel_message", "filters": {"channel": "C1"}},
                 status="error", error="The 'slack' connection isn't connected yet, so this hears nothing.")
EMAIL = _trigger("tr_3", "email", {"inbox_id": "inb_1", "address": "help@acme.test"})


def _subscription(**extra):
    return {"object": "subscription", "id": "sub_1", "channel_id": "ch_1", "workspace_id": None, "channels": None,
            "source": {"kind": "webhook", "name": "deploys"}, "wake": None, "filters": None, "status": "active",
            "error": None, "url": None, "last_event_at": None, "created_at": "2026-10-01T10:00:00Z", **extra}


def test_every_call_has_sync_and_aio_forms():
    agent = nc.Agent.from_id("ag_1")
    room = nc.Channel.from_id("ch_1")
    for bound in (agent.triggers, agent.add_trigger, agent.update_trigger, agent.remove_trigger, agent.pause_trigger,
                  agent.resume_trigger, agent.rehearse_trigger, room.subscribe, room.subscriptions,
                  nc.Subscription._new(raw=_subscription()).unsubscribe, nc.Connection.from_name("slack").events):
        assert asyncio.iscoroutinefunction(bound.aio), bound


def test_on_event_takes_a_connection_or_its_name():
    assert repr(nc.OnEvent("hubspot", "contact_created")) == "OnEvent('hubspot', 'contact_created')"
    with pytest.raises(TypeError):
        nc.OnEvent(42, "channel_message")
    with pytest.raises(TypeError):
        asyncio.run(nc.Agent.from_id("ag_1").add_trigger.aio("0 8 * * *"))


def test_create_sends_webhook_and_event_triggers(api, client):
    api.get("/v1/connections/slack").respond(json={"object": "connection", "id": "cn_1", "name": "slack",
                                                   "integration": "slack", "status": "connected"})
    create = api.post("/v1/agents").respond(json=AGENT)
    nc.Agent.create(
        "support", instructions="Answer #support.",
        triggers=[nc.OnWebhook(name="orders", conversation="order-{order.id}"),
                  nc.OnEvent(nc.Connection.from_name("slack"), "channel_message", channel="C1", message="Answer it")],
    )
    assert body(create.calls.last.request) == {
        "name": "support", "instructions": "Answer #support.",
        "triggers": [
            {"kind": "webhook", "name": "orders", "conversation": "order-{order.id}"},
            {"kind": "event", "connection": "slack", "event": "channel_message", "filters": {"channel": "C1"},
             "message": "Answer it"},
        ],
    }


def test_an_event_on_an_account_connected_in_the_app_names_it_by_its_ref(api, client):
    ref = "credential:9b2a1c5e-7d9f-4a31-8f6d-3f1d2c4b8a7e"
    api.get(f"/v1/connections/{ref}").respond(json={"object": "connection", "id": ref, "name": "WhatsApp",
                                                    "origin": "app", "integration": "whatsapp",
                                                    "status": "connected"})
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    added = api.post("/v1/agents/ag_1/triggers").respond(json=_trigger("tr_7", "event", {"connection": ref}))
    nc.Agent.from_id("ag_1").add_trigger(nc.OnEvent(nc.Connection.from_id(ref), "receive_message"))
    assert body(added.calls.last.request) == {"kind": "event", "connection": ref, "event": "receive_message",
                                              "filters": {}}


def test_from_name_converges_triggers_and_keeps_webhooks_and_mail(api, client):
    api.get("/v1/agents").respond(json=listing(AGENT))
    api.get("/v1/agents/ag_1/triggers").respond(json=listing(WEBHOOK, EVENT, EMAIL))
    removed = api.delete("/v1/agents/ag_1/triggers/tr_5").respond(json={"id": "tr_5", "deleted": True})
    added = api.post("/v1/agents/ag_1/triggers").respond(json=_trigger("tr_6", "event", {}))
    reread = api.get("/v1/agents/ag_1").respond(json=AGENT)
    agent = nc.Agent.from_name(
        "support", create_if_missing=True, instructions="hi",
        triggers=[nc.OnWebhook(name="orders"), nc.OnEvent("slack", "app_mention")],
    )
    assert agent.id == "ag_1"
    assert removed.call_count == 1  # the old event, not the webhook (its URL stays) nor the inbox's mail
    assert body(added.calls.last.request) == {"kind": "event", "connection": "slack", "event": "app_mention",
                                              "filters": {}}
    assert reread.call_count == 1


def test_a_matching_definition_sends_no_trigger_writes(api, client):
    api.get("/v1/agents").respond(json=listing(AGENT))
    api.get("/v1/agents/ag_1/triggers").respond(json=listing(WEBHOOK, EVENT, EMAIL))
    writes = [api.post("/v1/agents/ag_1/triggers"), api.delete(path__startswith="/v1/agents/ag_1/triggers/"),
              api.get("/v1/agents/ag_1")]
    agent = nc.Agent.from_name("support", create_if_missing=True, instructions="hi",
                               triggers=[nc.OnWebhook(name="orders"), nc.OnEvent("slack", "channel_message",
                                                                                 channel="C1")])
    agent.hydrate()
    assert all(route.call_count == 0 for route in writes)


def test_triggers_add_and_remove(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    listed = api.get("/v1/agents/ag_1/triggers").respond(json=listing(WEBHOOK, EVENT, EMAIL))
    add = api.post("/v1/agents/ag_1/triggers").respond(json=WEBHOOK)
    delete = api.delete(path__regex=r"/v1/agents/ag_1/triggers/tr_\d").respond(json={"deleted": True})

    agent = nc.Agent.from_id("ag_1")
    webhook, event, email = agent.triggers()
    assert (webhook.url, webhook.defined, webhook.next_run) == ("https://wh_1.example.com", True, None)
    assert (event.status, event.error.startswith("The 'slack' connection"), event.spec["filters"]) == (
        "error", True, {"channel": "C1"})
    assert (email.defined, email.spec["address"]) == (False, "help@acme.test")

    added = agent.add_trigger(nc.OnWebhook(name="orders", message="A new order"))
    assert body(add.calls.last.request) == {"kind": "webhook", "name": "orders", "message": "A new order"}
    assert added.url == WEBHOOK["url"]

    agent.remove_trigger(event)
    agent.remove_trigger("tr_2")
    assert [c.request.url.path for c in delete.calls] == ["/v1/agents/ag_1/triggers/tr_5",
                                                         "/v1/agents/ag_1/triggers/tr_2"]
    # A definition is matched against what the agent has.
    agent.remove_trigger(nc.OnEvent("slack", "channel_message", channel="C1"))
    assert delete.calls.last.request.url.path == "/v1/agents/ag_1/triggers/tr_5"
    assert listed.call_count == 2
    with pytest.raises(nc.NotFound):
        agent.remove_trigger(nc.OnWebhook(name="refunds"))


def test_a_trigger_changes_in_place(api, client):
    """A schedule moves to a new time without a second one beside it; its id, and a webhook's URL, stay."""
    schedule = _trigger("tr_8", "cron", {"cron": "0 8 * * 1-5", "tz": "Europe/London", "message": "Brief me."})
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.get("/v1/agents/ag_1/triggers").respond(json=listing(schedule, WEBHOOK))
    moved = {**schedule, "spec": {"cron": "30 7 * * 1-5", "tz": "Europe/London", "message": "Brief me."}}
    patch = api.patch(path__regex=r"/v1/agents/ag_1/triggers/tr_\d").respond(json=moved)

    agent = nc.Agent.from_id("ag_1")
    changed = agent.update_trigger("tr_8", cron=nc.Cron("30 7 * * 1-5", tz="Europe/London"))
    assert patch.calls.last.request.url.path == "/v1/agents/ag_1/triggers/tr_8"
    assert body(patch.calls.last.request) == {"cron": "30 7 * * 1-5", "tz": "Europe/London"}
    assert (changed.id, changed.spec["cron"]) == ("tr_8", "30 7 * * 1-5")

    # The definition you added finds it, as for remove_trigger; None clears what it was told.
    agent.update_trigger(nc.Cron("0 8 * * 1-5", tz="Europe/London", message="Brief me."), message=None)
    assert body(patch.calls.last.request) == {"message": None}
    agent.update_trigger(nc.OnWebhook(name="orders"), message="A new order.", conversation="order-{order.id}")
    assert patch.calls.last.request.url.path == "/v1/agents/ag_1/triggers/tr_2"
    assert body(patch.calls.last.request) == {"message": "A new order.", "conversation": "order-{order.id}"}
    with pytest.raises(ValueError):
        agent.update_trigger("tr_8")
    with pytest.raises(TypeError):
        agent.update_trigger("tr_8", cron="30 7 * * 1-5")
    assert patch.call_count == 3


def test_one_trigger_pauses_resumes_and_is_tried_with_a_sample(api, client):
    """A trigger paused alone says so, with what makes it live again; a test sends the sample it's given."""
    paused = {**WEBHOOK, "status": "paused", "paused": True, "state": "paused",
              "reason": "Paused: it doesn't wake the agent until it's resumed.", "fix": {"action": "resume"},
              "set_by": {"kind": "agent", "agent_id": "ag_9"}, "read_only": False,
              "actions": ["resume", "test", "update", "remove"], "next_run_at": None}
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.get("/v1/agents/ag_1/triggers").respond(json=listing(WEBHOOK, EVENT))
    pause = api.post("/v1/agents/ag_1/triggers/tr_2/pause").respond(json=paused)
    resume = api.post("/v1/agents/ag_1/triggers/tr_2/resume").respond(json={**WEBHOOK, "state": "live"})
    test = api.post("/v1/agents/ag_1/triggers/tr_2/test").respond(
        status_code=202, json={"object": "operation", "id": "op_1", "kind": "agent.rehearse", "status": "queued"})
    patch = api.patch("/v1/agents/ag_1/triggers/tr_5").respond(json=EVENT)

    agent = nc.Agent.from_id("ag_1")
    held = agent.pause_trigger(nc.OnWebhook(name="orders"))
    assert pause.called and (held.paused, held.state, held.fix, held.actions) == (
        True, "paused", {"action": "resume"}, ["resume", "test", "update", "remove"])
    assert (held.set_by, held.read_only, held.reason.startswith("Paused")) == (
        {"kind": "agent", "agent_id": "ag_9"}, False, True)
    assert agent.resume_trigger("tr_2").state == "live" and resume.called

    run = agent.rehearse_trigger("tr_2", sample={"order": "A-17"})
    assert body(test.calls.last.request) == {"sample": {"order": "A-17"}} and run.id == "op_1"
    agent.rehearse_trigger("tr_2")
    assert test.calls.last.request.content == b""  # a sample of its own

    agent.update_trigger("tr_5", filters={"channel": "C2"})
    assert body(patch.calls.last.request) == {"filters": {"channel": "C2"}}
    agent.update_trigger("tr_5", mode="all")
    assert body(patch.calls.last.request) == {"mode": "all"}
    # A view from before these fields reads as live, set up by a person.
    [old, _] = agent.triggers()
    assert (old.state, old.paused, old.set_by, old.actions) == ("live", False, {"kind": "person", "agent_id": None}, [])


def test_a_webhook_is_removed_by_its_name(api, client):
    """Webhook names are unique on an agent: removing one by its definition matches its name, whatever else it
    was added with. Any other definition matches whole."""
    hook = _trigger("tr_7", "webhook", {"name": "orders", "message": "A new order", "conversation": "order-{order.id}"},
                    url="https://wh_7.example.com")
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.get("/v1/agents/ag_1/triggers").respond(json=listing(hook, EVENT))
    delete = api.delete("/v1/agents/ag_1/triggers/tr_7").respond(json={"deleted": True})

    agent = nc.Agent.from_id("ag_1")
    agent.remove_trigger(nc.OnWebhook(name="orders"))
    assert delete.call_count == 1
    with pytest.raises(nc.NotFound):
        agent.remove_trigger(nc.OnWebhook(name="refunds"))
    with pytest.raises(nc.NotFound):
        agent.remove_trigger(nc.OnEvent("slack", "channel_message"))


def test_connection_events_list_what_on_event_can_listen_for(api, client):
    read = api.get("/v1/connections/slack").respond(json={"object": "connection", "id": "con_s", "name": "slack"})
    route = api.get("/v1/integrations/slack/events").respond(json=listing(
        {"object": "integration_event", "name": "channel_message", "description": "On Channel Message",
         "filters": {"channel": "Optional — fire only for events in this channel."}, "required_filters": []},
    ))
    with nc.as_user(USER_ID):
        events = nc.Connection.from_name("slack", integration="slack", create_if_missing=True).events()
    assert route.called and read.call_count == 0  # the catalog, read without the connection
    assert "NoClick-User" not in route.calls.last.request.headers
    assert isinstance(events[0], nc.IntegrationEvent)
    assert [(e.name, list(e.filters)) for e in events] == [("channel_message", ["channel"])]


# --- channel subscriptions ------------------------------------------------------------------

def test_subscribe_a_channel_to_an_apps_events(api, client):
    api.get("/v1/connections/stripe").respond(json={"object": "connection", "id": "cn_s", "name": "stripe",
                                                    "integration": "stripe", "status": "connected"})
    sub = api.post("/v1/channels/ch_1/subscriptions").respond(json=_subscription(
        source={"kind": "event", "connection": "stripe", "event": "invoice_payment_failed", "filters": {}},
        wake=["ag_1"]))
    stripe = nc.Connection.from_name("stripe")
    made = nc.Channel.from_id("ch_1").subscribe(nc.OnEvent(stripe, "invoice_payment_failed"),
                                                wake=[nc.Agent.from_id("ag_1")])
    assert body(sub.calls.last.request) == {
        "source": {"kind": "event", "connection": "stripe", "event": "invoice_payment_failed", "filters": {}},
        "wake": ["ag_1"],
    }
    assert isinstance(made, nc.Subscription) and made.wake == ["ag_1"] and made.status == "active"


def test_subscribe_a_webhook(api, client):
    sub = api.post("/v1/channels/ch_1/subscriptions").respond(json=_subscription(
        wake="all", filters={"status": "failed"}, url="https://wh_2.example.com"))
    room = nc.Channel.from_id("ch_1")
    deploys = room.subscribe(nc.OnWebhook(name="deploys"), wake="all", filters={"status": "failed"})
    assert body(sub.calls.last.request) == {
        "source": {"kind": "webhook", "name": "deploys"}, "wake": "all", "filters": {"status": "failed"},
    }
    assert (deploys.url, deploys.filters) == ("https://wh_2.example.com", {"status": "failed"})
    room.subscribe(nc.OnWebhook(name="logs"))
    # wake=None is sent: the event is posted and wakes no one.
    assert body(sub.calls.last.request) == {"source": {"kind": "webhook", "name": "logs"}, "wake": None}


def test_subscribe_refuses_what_a_channel_cant_take(api, client):
    room = nc.Channel.from_id("ch_1")
    with pytest.raises(ValueError, match="one conversation"):
        room.subscribe(nc.OnWebhook(name="orders", conversation="order-{order.id}"))
    with pytest.raises(ValueError, match="one conversation"):
        room.subscribe(nc.OnEvent("stripe", "invoice_paid", conversation="invoice-{id}"))
    with pytest.raises(TypeError, match=r"on OnEvent itself: OnEvent\(stripe, .invoice_payment_failed.,"):
        room.subscribe(nc.OnEvent("stripe", "invoice_paid"), filters={"amount": 100})
    with pytest.raises(TypeError, match="source"):
        room.subscribe(nc.Cron("0 9 * * *"))
    with pytest.raises(TypeError, match="wake="):
        room.subscribe(nc.OnWebhook(name="deploys"), wake="billing")
    assert not api.calls


def test_subscriptions_list_and_unsubscribe(api, client):
    api.get("/v1/channels/ch_1/subscriptions").respond(json=listing(_subscription(
        status="error", error="The channel is closed, so it hears nothing.")))
    gone = api.delete("/v1/channels/ch_1/subscriptions/sub_1").respond(json={"id": "sub_1", "deleted": True})
    [sub] = nc.Channel.from_id("ch_1").subscriptions()
    assert (sub.status, sub.error) == ("error", "The channel is closed, so it hears nothing.")
    sub.unsubscribe()
    assert gone.called


def test_an_apps_post_says_which_subscription_and_carries_the_event(api, client):
    api.get("/v1/channels/ch_1/messages").respond(json=listing({
        "id": "msg_1", "channel_id": "ch_1", "author": {"type": "app", "id": None, "name": "Stripe"},
        "text": "Stripe invoice.payment_failed: invoice in_42", "mentions": [], "created_at": "2026-10-01T10:00:00Z",
        "subscription_id": "sub_1", "event": {"type": "invoice.payment_failed", "id": "evt_1"},
    }))
    [message] = nc.Channel.from_id("ch_1").messages()
    assert (message.author.type, message.author.name) == ("app", "Stripe")
    assert message.subscription_id == "sub_1" and message.event["id"] == "evt_1"
