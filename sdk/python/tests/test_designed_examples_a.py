"""What writing the examples asked of agents, people and triggers (designed, not built yet):
people as tools and hand-offs, time, networks and shells, model usage, answering held calls
from code, live conversations, conversation keys on triggers, one queue turn at a time, and
the harness and inbox lookups."""

import asyncio

import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID, agent_row, body, listing, operation, user_row

AGENT = agent_row(id="ag_1", name="support")


# --- definitions: time, network, shell ------------------------------------------------

def test_create_sends_timezone_network_and_shell(api, client):
    create = api.post("/v1/agents").respond(json={**AGENT, "timezone": "Europe/Berlin", "network": ["pypi.org"],
                                                  "shell": False})
    agent = nc.Agent.create("support", instructions="hi", timezone="Europe/Berlin", network=("pypi.org", "*.npmjs.org"),
                            shell=False)
    assert body(create.calls.last.request) == {
        "name": "support", "instructions": "hi", "timezone": "Europe/Berlin",
        "network": ["pypi.org", "*.npmjs.org"], "shell": False,
    }
    assert (agent.timezone, agent.network, agent.shell) == ("Europe/Berlin", ["pypi.org"], False)


def test_network_is_a_bool_or_a_list_of_hosts():
    with pytest.raises(TypeError, match="list of hosts"):
        nc.Agent.from_name("support", create_if_missing=True, instructions="hi", network="pypi.org")
    with pytest.raises(TypeError):
        asyncio.run(nc.Sandbox.create.aio(network=[42]))


def test_from_name_converges_the_new_fields_and_none_clears_the_timezone(api, client):
    api.get("/v1/agents").respond(json=listing({**AGENT, "timezone": "UTC", "network": True, "shell": True}))
    patch = api.patch("/v1/agents/ag_1").respond(json={**AGENT, "timezone": None, "network": False})
    agent = nc.Agent.from_name("support", create_if_missing=True, instructions="hi", timezone=None, network=False,
                               shell=True)
    agent.hydrate()
    assert body(patch.calls.last.request) == {"timezone": None, "network": False}


def test_update_sends_network_timezone_and_shell(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    patch = api.patch("/v1/agents/ag_1").respond(json={**AGENT, "network": ["api.stripe.com"]})
    agent = nc.Agent.from_id("ag_1").update(network=["api.stripe.com"], timezone="America/New_York", shell=True)
    assert body(patch.calls.last.request) == {"network": ["api.stripe.com"], "timezone": "America/New_York", "shell": True}
    assert agent.network == ["api.stripe.com"]


def test_repos_clone_checkouts_from_a_connection_and_a_repo(api, client):
    api.get("/v1/connections/github").respond(json={"object": "connection", "id": "cn_gh", "name": "github",
                                                    "integration": "github", "status": "connected"})
    api.get("/v1/repos/rp_1").respond(json={"object": "repo", "id": "rp_1", "name": "site"})
    create = api.post("/v1/agents").respond(json=AGENT)
    github = nc.Connection.from_name("github")
    nc.Agent.create("fixer", instructions="hi", repos=[
        github.checkout("acme/web", push=["agent/*"]), nc.Repo.from_id("rp_1").checkout(branch="main", path="site"),
    ])
    assert body(create.calls.last.request)["repos"] == [
        {"connection": "github", "repository": "acme/web", "push": ["agent/*"]},
        {"repo_id": "rp_1", "branch": "main", "path": "site"},
    ]
    with pytest.raises(TypeError, match="checkout"):
        asyncio.run(nc.Agent.create.aio("fixer", instructions="hi", repos=["acme/web"]))


def test_update_replaces_the_repos(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    patch = api.patch("/v1/agents/ag_1").respond(json=AGENT)
    nc.Agent.from_id("ag_1").update(repos=[nc.Repo.from_id("rp_1").checkout()])
    assert body(patch.calls.last.request) == {"repos": [{"repo_id": "rp_1"}]}
    nc.Agent.from_id("ag_1").update(repos=[])
    assert body(patch.calls.last.request) == {"repos": []}


def test_a_sandbox_takes_a_list_of_hosts(api, client):
    create = api.post("/v1/sandboxes").respond(json={"object": "sandbox", "id": "sb_1", "status": "running",
                                                     "network": ["pypi.org"]})
    sandbox = nc.Sandbox.create(image="python", network=["pypi.org"])
    assert body(create.calls.last.request) == {"image": "python", "network": ["pypi.org"]}
    assert sandbox.network == ["pypi.org"]


def test_a_cron_read_in_the_users_timezone(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    add = api.post("/v1/agents/ag_1/triggers").respond(json={"object": "agent_trigger", "id": "tr_1", "kind": "cron",
                                                            "spec": {"cron": "0 8 * * *", "tz": "user"}})
    nc.Agent.from_id("ag_1").add_trigger(nc.Cron("0 8 * * *", tz="user", message="Brief me"))
    assert body(add.calls.last.request) == {"kind": "cron", "cron": "0 8 * * *", "tz": "user", "message": "Brief me"}


# --- people as tools --------------------------------------------------------------------

def test_people_in_tools_say_who_they_reach(api, client):
    api.get("/v1/users/user_42").respond(json=user_row())
    create = api.post("/v1/agents").respond(json=AGENT)
    ops = nc.Human(email="ops@acme.com", phone="+14155550123")
    nc.Agent.create("support", instructions="hi", tools=[
        "search", ops.only("notify", "ask"), nc.Human(), nc.User.from_id(USER_ID).human.only("hand_off"),
    ])
    assert body(create.calls.last.request)["tools"] == [
        "search",
        {"human": {"email": "ops@acme.com", "phone": "+14155550123"}, "tools": ["notify", "ask"]},
        {"human": {"user": True}, "tools": ["notify", "ask", "hand_off"]},
        {"human": {"user_id": USER_ID}, "tools": ["hand_off"]},
    ]


def test_only_takes_the_three_tools():
    with pytest.raises(ValueError, match="'notify', 'ask' and 'hand_off'"):
        nc.Human(email="ops@acme.com").only("approve")
    with pytest.raises(ValueError):
        nc.Human(email="ops@acme.com").only()
    assert isinstance(nc.Human(email="ops@acme.com").only("ask"), nc.HumanOperations)


def test_hand_back_gives_the_conversation_back(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    route = api.post("/v1/agents/ag_1/conversations/ticket%2F1841/hand_back").respond(204)
    nc.Agent.from_id("ag_1").hand_back("ticket/1841", user=USER_ID)
    assert route.calls.last.request.headers["NoClick-User"] == USER_ID


def test_a_conversation_says_when_its_handed_off_and_what_its_models_used(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.get("/v1/agents/ag_1/conversations").respond(json=listing({
        "conversation": "ticket-1841", "user_id": USER_ID, "turns": 3, "cost_usd": 0.02, "status": "handed_off",
        "handed_off_to": "lead@acme.com",
        "model_usage": {"input_tokens": 1200, "output_tokens": 300, "cached_tokens": 800, "usd": 0.0123},
    }))
    [convo] = nc.Agent.from_id("ag_1").conversations(user_filter=nc.ALL_USERS)
    assert (convo.status, convo.handed_off_to) == ("handed_off", "lead@acme.com")
    assert convo.model_usage == nc.ModelUsage(1200, 300, 800, 0.0123, convo.model_usage.raw)


# --- replies and live conversations ------------------------------------------------------

def test_a_reply_carries_its_model_usage(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.post("/v1/agents/ag_1/messages").respond(json=operation(
        "op_m", "agent.message", "succeeded",
        result={"text": "Done.", "model_usage": {"input_tokens": 10, "output_tokens": 5, "cached_tokens": 0, "usd": 0.001}}))
    reply = nc.Agent.from_id("ag_1").message("hi")
    assert (reply.model_usage.input_tokens, reply.model_usage.output_tokens, reply.model_usage.usd) == (10, 5, 0.001)
    api.post("/v1/agents/ag_1/messages").respond(json=operation("op_n", "agent.message", "succeeded", result={"text": "x"}))
    assert nc.Agent.from_id("ag_1").message("hi").model_usage is None


WATCH = (
    "event: message\ndata: {\"role\": \"person\", \"text\": \"I've refunded it.\", \"operation_id\": null}\n\n"
    "event: status\ndata: {\"status\": \"active\"}\n\n"
    "event: tool_call\ndata: {\"tool\": \"stripe__create_refund\", \"arguments\": {\"amount\": 95}, "
    "\"operation_id\": \"op_7\", \"held\": {\"request_id\": \"hr_1\", \"url\": \"https://noclick.com/h/hr_1\", "
    "\"approver\": \"owner\"}}\n\n"
    "event: message\ndata: {\"role\": \"assistant\", \"text\": \"Refunded.\", \"operation_id\": \"op_7\"}\n\n"
)


def test_watch_follows_a_conversation(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    route = api.get("/v1/agents/ag_1/conversations/ticket-1841/events").respond(
        200, content=WATCH.encode(), headers={"content-type": "text/event-stream"})
    events = list(nc.Agent.from_id("ag_1").watch("ticket-1841", user=USER_ID))
    assert [(e.type, e.role, e.text) for e in events] == [
        ("message", "person", "I've refunded it."), ("status", None, None),
        ("tool_call", None, None), ("message", "assistant", "Refunded."),
    ]
    assert events[1].status == "active"
    assert (events[2].held["url"], events[2].operation_id, events[2].arguments) == (
        "https://noclick.com/h/hr_1", "op_7", {"amount": 95})
    request = route.calls.last.request
    assert request.headers["Accept"] == "text/event-stream" and request.headers["NoClick-User"] == USER_ID


def test_a_streamed_reply_carries_its_model_usage(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    done = ("event: done\ndata: {\"text\": \"ok\", \"conversation\": \"c\", \"operation_id\": \"op_9\", "
            "\"model_usage\": {\"input_tokens\": 3, \"output_tokens\": 1, \"cached_tokens\": 0, \"usd\": 0.0001}}\n\n")
    api.post("/v1/agents/ag_1/messages").respond(200, content=done.encode())
    [event] = list(nc.Agent.from_id("ag_1").stream("hi"))
    assert (event.operation_id, event.reply.model_usage.input_tokens) == ("op_9", 3)


# --- held calls: answered from code -------------------------------------------------------

def test_approve_and_decline_carry_a_note(api, client):
    api.get("/v1/humans/requests").respond(json=listing(
        {"id": "hr_1", "operation_id": "op_h", "kind": "approve", "status": "pending", "details": {}}))
    answer = api.post("/v1/humans/requests/hr_1/answer").mock(side_effect=[
        httpx.Response(200, json={"id": "hr_1", "kind": "approve", "status": "answered", "note": "Fine."}),
        httpx.Response(200, json={"id": "hr_1", "kind": "approve", "status": "answered", "note": "Ask finance."}),
    ])
    [request] = nc.HumanRequest.list(status="pending", kind="approve")
    assert request.approve(note="Fine.") is request
    assert body(answer.calls.last.request) == {"approved": True, "note": "Fine."}
    assert (request.request_status, request.note) == ("answered", "Fine.")
    request.decline(note="Ask finance.")
    assert body(answer.calls.last.request) == {"approved": False, "note": "Ask finance."}
    assert request.note == "Ask finance."


def test_a_request_known_only_by_its_operation_cant_be_answered():
    with pytest.raises(ValueError, match="no request id"):
        nc.HumanRequest.from_id("op_h").approve()


def test_the_note_arrives_with_the_result(api, client):
    api.get("/v1/operations/op_h").respond(json=operation(
        "op_h", "human.approve", "succeeded", result={"approved": False, "note": "Over budget."}))
    request = nc.HumanRequest.from_id("op_h")
    request.hydrate()
    assert request.note == "Over budget."


# --- triggers: conversation keys, one queue turn at a time ---------------------------------

def test_triggers_take_a_conversation_template(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    add = api.post("/v1/agents/ag_1/triggers").respond(json={"object": "agent_trigger", "id": "tr_1", "kind": "event",
                                                            "spec": {}})
    agent = nc.Agent.from_id("ag_1")
    agent.add_trigger(nc.OnEvent("github", "issue.labeled", label="agent", conversation="issue-{issue.number}"))
    assert body(add.calls.last.request) == {
        "kind": "event", "connection": "github", "event": "issue.labeled", "filters": {"label": "agent"},
        "conversation": "issue-{issue.number}"}
    agent.add_trigger(nc.OnWebhook(name="orders", conversation="order-{order.id}"))
    assert body(add.calls.last.request) == {"kind": "webhook", "name": "orders", "conversation": "order-{order.id}"}
    agent.add_trigger(nc.OnQueue("signups", conversation="customer-{customer_id}"))
    assert body(add.calls.last.request) == {"kind": "queue", "queue": "signups", "batch_size": 1,
                                            "conversation": "customer-{customer_id}"}
    agent.add_trigger(nc.OnQueue("signups"))
    assert body(add.calls.last.request) == {"kind": "queue", "queue": "signups", "batch_size": 1}


def test_on_queue_takes_one_turn_at_a_time_and_keys_single_messages():
    assert repr(nc.OnQueue("signups", batch_size=5)) == "OnQueue('signups', batch_size=5)"
    with pytest.raises(TypeError, match="concurrency"):
        nc.OnQueue("signups", concurrency=3)  # an agent takes one turn at a time
    with pytest.raises(ValueError, match="batch holds several"):
        nc.OnQueue("signups", batch_size=10, conversation="c-{id}")


def test_an_approval_trigger_isnt_defined_by_code(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.get("/v1/agents/ag_1/triggers").respond(json=listing(
        {"object": "agent_trigger", "id": "tr_a", "kind": "approval", "spec": {}, "status": "active"}))
    [trigger] = nc.Agent.from_id("ag_1").triggers()
    assert (trigger.kind, trigger.defined) == ("approval", False)


# --- lookups: one harness, an agent's inboxes ---------------------------------------------

HARNESSES = listing(
    {"object": "harness", "name": "sdk", "default_model": "openrouter/x", "custom_models": True,
     "model_connection": "optional", "integrations": [], "streaming": "tokens", "shell": "code_capability"},
    {"object": "harness", "name": "opencode", "default_model": "opencode/x", "custom_models": True,
     "model_connection": "required", "integrations": ["openrouter"], "streaming": "final", "shell": "built_in"},
)


def test_harness_info_finds_one_by_name(api, client):
    api.get("/v1/harnesses").respond(json=HARNESSES)
    assert nc.Agent.harness_info("opencode").default_model == "opencode/x"
    with pytest.raises(nc.NotFound, match="'codex'") as caught:
        nc.Agent.harness_info("codex")
    assert "sdk, opencode" in caught.value.next_step


def test_inboxes_lists_the_inboxes_that_wake_it(api, client):
    api.get("/v1/agents/ag_1").respond(json={**AGENT, "user_id": USER_ID})
    route = api.get("/v1/inboxes").respond(json=listing(
        {"object": "inbox", "id": "inb_1", "address": "help@acme.test", "agent_id": "ag_1", "user_id": USER_ID}))
    [inbox] = nc.Agent.from_id("ag_1").inboxes()
    assert isinstance(inbox, nc.Inbox) and inbox.address == "help@acme.test"
    request = route.calls.last.request
    assert request.url.params["agent_id"] == "ag_1" and request.headers["NoClick-User"] == USER_ID
