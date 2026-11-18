import datetime

import httpx
import pytest

import noclick as nc
from platform_helpers import BASE, USER_ID, body, integration_row, listing, operation, trashed, user_row

AGENT = {
    "object": "agent", "id": "agt_1", "name": "sunrise-host", "model": "claude-x", "harness": "sdk",
    "instructions": "You take cake orders.", "tools": ["search"], "user_id": None,
    "workflow_id": "wf_1", "created_at": "2026-09-25T10:00:00Z",
}


# --- Human -------------------------------------------------------------------

def test_user_human_ask_waits_to_an_answer(api, client):
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row())
    create = api.post("/v1/humans/requests").respond(json={
        **operation(op_id="op_h", kind="human.ask"),
        "request": {"id": "hr_1", "url": "https://noclick.com/h/hr_1", "delivered_via": ["web"],
                    "undelivered": [{"channel": "email", "reason": "no email on file"}]},
    })
    api.get("/v1/operations/op_h/wait").respond(json=operation(
        op_id="op_h", kind="human.ask", status="succeeded", result={"choice": "Tue", "text": "after 3pm"},
    ))
    user = nc.User.get(USER_ID)
    op = user.human.ask("Which day?", options=["Mon", "Tue"], via="email", expires_in=datetime.timedelta(hours=1))
    assert isinstance(op, nc.HumanRequest) and isinstance(op, nc.Operation) and op.status == "awaiting_human"
    assert op.url == "https://noclick.com/h/hr_1" and op.delivered_via == ["web"]
    assert op.undelivered[0]["channel"] == "email"
    assert body(create.calls.last.request) == {
        "kind": "ask", "to": {"user": True}, "message": "Which day?", "options": ["Mon", "Tue"],
        "via": ["email"], "expires_in_s": 3600,
    }
    assert create.calls.last.request.headers["NoClick-User"] == USER_ID
    answer = op.wait()
    assert (answer.choice, answer.text) == ("Tue", "after 3pm")
    assert op.url == "https://noclick.com/h/hr_1"  # the request view survives the wait


def test_approve_waits_to_bool_and_carries_details(api, client):
    create = api.post("/v1/humans/requests").respond(json=operation(op_id="op_a", kind="human.approve"))
    api.get("/v1/operations/op_a/wait").respond(
        json=operation(op_id="op_a", kind="human.approve", status="succeeded", result={"approved": False})
    )
    with nc.as_user("user_42"):
        op = nc.Human().approve("Send the weekly summary?", details={"recipients": 12})
    assert op.wait() is False
    sent = body(create.calls.last.request)
    assert sent["details"] == {"recipients": 12} and sent["via"] == "auto" and sent["to"] == {"user": True}
    assert create.calls.last.request.headers["NoClick-User"] == "user_42"


def test_notify_succeeds_immediately_and_email_target(api, client):
    route = api.post("/v1/humans/requests").respond(
        json=operation(op_id="op_n", kind="human.notify", status="succeeded", result={})
    )
    op = nc.Human(email="ops@acme.ai").notify("Deploy finished")
    assert op.done and op.wait() is None
    assert body(route.calls.last.request)["to"] == {"email": "ops@acme.ai"}
    assert "NoClick-User" not in route.calls.last.request.headers


def test_human_meaning_the_user_lets_the_server_decide(api, client):
    route = api.post("/v1/humans/requests").respond(400, json={"error": {
        "type": "invalid_request", "message": "to.user needs a user to act for.",
        "next_step": "Send the NoClick-User header naming the user, or pass to.email."}})
    with pytest.raises(nc.InvalidRequest) as info:
        nc.Human().ask("hello?")
    assert "NoClick-User" in info.value.next_step
    assert body(route.calls.last.request)["to"] == {"user": True}


CONNECTION = {"object": "connection", "id": "con_1", "name": "gmail", "integration": "gmail", "user_id": None,
              "status": "pending", "connect_link": None}

@pytest.mark.parametrize("pinned", [
    lambda: nc.Client.for_session("nk_sess_x", base_url=BASE),  # a user session
    lambda: nc.Client(api_key="nk_live_pinned", base_url=BASE),  # a key pinned with user_id
])
def test_a_user_pinned_client_reaches_its_user(api, client, pinned):
    route = api.post("/v1/humans/requests").respond(json=operation(op_id="op_h", kind="human.ask"))
    looked_up = api.get("/v1/connections/gmail").respond(json=CONNECTION)
    links = api.post("/v1/connections/gmail/connect_links").respond(json={
        "object": "connect_link", "url": "https://noclick.com/c/9", "expires_at": None,
        "operation": operation(op_id="op_c", kind="credential.connect"),
    })
    human = nc.Human(client=pinned())
    human.ask("Which plan?", options=["A", "B"])
    sent = route.calls.last.request
    assert body(sent)["to"] == {"user": True} and "NoClick-User" not in sent.headers
    human.connect("gmail")
    assert body(links.calls.last.request)["send_to"] == {"user": True}
    assert "NoClick-User" not in links.calls.last.request.headers and looked_up.call_count == 0


def test_connect_links_refuse_a_phone_only_recipient(api, client):
    looked_up = api.get("/v1/connections/gmail").respond(json=CONNECTION)
    route = api.post("/v1/connections/gmail/connect_links").respond(json={})
    gmail = nc.Connection.from_name("gmail")
    for call in (lambda: gmail.connect_link(send_to="+14155550100"),
                 lambda: gmail.request(send_to={"phone": "+14155550100"}),
                 lambda: nc.Human(phone="+14155550100").connect("gmail")):
        with pytest.raises(nc.InvalidRequest) as info:
            call()
        assert "email only" in info.value.message and "url yourself" in info.value.next_step
    assert not route.calls and not looked_up.calls  # refused before anything is sent
    # A person with an email as well gets the link by email.
    route.respond(json={"object": "connect_link", "url": "https://noclick.com/c/9", "expires_at": None,
                        "operation": operation(op_id="op_c", kind="credential.connect")})
    nc.Human(email="ana@example.com", phone="+14155550100").connect("gmail")
    assert body(route.calls.last.request)["send_to"] == {"email": "ana@example.com", "phone": "+14155550100"}


def test_human_connect_returns_a_connect_link(api, client):
    looked_up = api.get("/v1/connections/gmail").respond(json=CONNECTION)
    route = api.post("/v1/connections/gmail/connect_links").respond(json={
        "object": "connect_link", "url": "https://noclick.com/c/9", "expires_at": None,
        "operation": operation(op_id="op_c", kind="credential.connect"),
    })
    link = nc.Human(user="user_42").connect("gmail", reason="to send your summary")
    assert isinstance(link, nc.ConnectLink) and link.url.endswith("/c/9")
    assert body(route.calls.last.request)["send_to"] == {"user": True}
    assert route.calls.last.request.headers["NoClick-User"] == "user_42" and looked_up.call_count == 0


def test_lazy_user_human_creates_the_user_first(api, client):
    lookup = api.get("/v1/users/user_42").respond(404, json={"error": {"type": "not_found", "message": "No user."}})
    create = api.post("/v1/users").respond(json=user_row())
    route = api.post("/v1/humans/requests").respond(json=operation(kind="human.notify", status="succeeded"))
    nc.User.from_id("user_42", create_if_missing=True).human.notify("hi")
    assert route.calls.last.request.headers["NoClick-User"] == "user_42"
    assert (lookup.call_count, create.call_count) == (1, 1)


# --- Agent -------------------------------------------------------------------

def test_from_name_creates_when_missing_and_messages(api, client):
    lookup = api.get("/v1/agents").respond(json=listing())
    create = api.post("/v1/agents").respond(json=AGENT)
    send = api.post("/v1/agents/agt_1/messages").respond(json=operation(op_id="op_m", kind="agent.message", status="queued"))
    api.get("/v1/operations/op_m/wait").mock(side_effect=[
        httpx.Response(200, json=operation(op_id="op_m", kind="agent.message", status="running")),
        httpx.Response(200, json=operation(op_id="op_m", kind="agent.message", status="succeeded", result={
            "text": "Lemon cake today.", "conversation": "conv_1", "tool_calls": [{"tool": "search"}],
        })),
    ])
    agent = nc.Agent.from_name("sunrise-host", create_if_missing=True, instructions="You take cake orders.",
                               tools=nc.Toolkit(["search"]))
    assert agent.name == "sunrise-host" and lookup.call_count == 0
    reply = agent.message("What's on today?")
    assert reply.text == "Lemon cake today." and str(reply) == reply.text
    assert (reply.conversation, reply.tool_calls, reply.operation_id) == ("conv_1", [{"tool": "search"}], "op_m")
    assert lookup.calls.last.request.url.params["name"] == "sunrise-host"
    assert body(create.calls.last.request) == {
        "name": "sunrise-host", "instructions": "You take cake orders.", "tools": ["search"],
    }
    assert body(send.calls.last.request) == {"text": "What's on today?"}


def test_from_name_finds_existing_and_converges_it_to_the_code(api, client):
    api.get("/v1/agents").respond(json=listing(AGENT))
    create = api.post("/v1/agents").respond(json=AGENT)
    patch = api.patch("/v1/agents/agt_1").respond(json={**AGENT, "instructions": "x", "can_request": ["gmail"]})
    api.get("/v1/integrations").respond(json=listing(integration_row("gmail")))
    [gmail] = nc.Connection.integrations("gmail")
    agent = nc.Agent.from_name("sunrise-host", create_if_missing=True, instructions="x", tools=AGENT["tools"],
                               can_request=[gmail])
    assert agent.id == "agt_1" and create.call_count == 0
    # Only what differs from the stored definition is sent; grants aren't part of it.
    assert body(patch.calls.last.request) == {"instructions": "x", "can_request": ["gmail"]}
    assert agent.can_request == ["gmail"]

    same = nc.Agent.from_name("sunrise-host", create_if_missing=True, instructions=AGENT["instructions"])
    assert same.id == "agt_1" and patch.call_count == 1


def test_from_name_inside_as_user_never_matches_a_shared_account_agent(api, client):
    lookup = api.get("/v1/agents").respond(json=listing(AGENT))  # the account's, user_id None
    create = api.post("/v1/agents").respond(json={**AGENT, "id": "agt_2", "user_id": USER_ID})
    with nc.as_user("user_42"):
        own = nc.Agent.from_name("sunrise-host", create_if_missing=True, instructions="x")
        assert own.id == "agt_2" and create.call_count == 1
        # Without a definition too: the user's name finds only their own agent.
        with pytest.raises(nc.NotFound):
            nc.Agent.from_name("sunrise-host").hydrate()
    lookup.respond(json=listing(AGENT, {**AGENT, "id": "agt_2", "user_id": USER_ID}))
    with nc.as_user("user_42"):
        assert nc.Agent.from_name("sunrise-host").id == "agt_2"
    assert nc.Agent.from_name("sunrise-host").id == "agt_1"


def test_an_explicit_none_in_from_name_clears_the_field(api, client):
    coder = {**AGENT, "harness": "claude_code", "model": "sonnet", "model_connection": "claude",
             "budget_usd_per_month": 20}
    api.get("/v1/agents").respond(json=listing(coder))
    patch = api.patch("/v1/agents/agt_1").mock(
        side_effect=lambda request: httpx.Response(200, json={**coder, **body(request)}))
    # Back to sdk: the model connection and the budget go, like update(model_connection=None).
    agent = nc.Agent.from_name("sunrise-host", create_if_missing=True, instructions=AGENT["instructions"],
                               harness="sdk", model="claude-x", model_connection=None, budget_usd_per_month=None)
    assert agent.model_connection is None
    assert body(patch.calls.last.request) == {
        "harness": "sdk", "model": "claude-x", "model_connection": None, "budget_usd_per_month": None}
    # Left out, they're never touched.
    nc.Agent.from_name("sunrise-host", create_if_missing=True, instructions=AGENT["instructions"],
                       harness="claude_code", model="sonnet").hydrate()
    assert patch.call_count == 1
    # A new agent is created without the cleared fields.
    api.get("/v1/agents").respond(json=listing())
    create = api.post("/v1/agents").respond(json=AGENT)
    nc.Agent.from_name("sunrise-host", create_if_missing=True, instructions="x", model_connection=None).hydrate()
    assert body(create.calls.last.request) == {"name": "sunrise-host", "instructions": "x"}


def test_from_name_missing_without_create(api, client):
    api.get("/v1/agents").respond(json=listing())
    with pytest.raises(nc.NotFound):
        nc.Agent.from_name("ghost").hydrate()


def test_from_name_requires_instructions_to_create():
    with pytest.raises(ValueError):
        nc.Agent.from_name("x", create_if_missing=True)


def test_agent_in_user_scope_and_conversation(api, client):
    user_agent = {**AGENT, "user_id": USER_ID}
    create = api.post("/v1/agents").respond(json=user_agent)
    send = api.post("/v1/agents/agt_1/messages").respond(json=operation(
        op_id="op_m", kind="agent.message", status="succeeded", result={"text": "ok", "conversation": "c/1"}))
    history = api.get("/v1/agents/agt_1/conversations/conv-1").respond(json={"messages": [
        {"role": "user", "text": "hi", "created_at": "2026-09-25T10:00:00Z"},
        {"role": "assistant", "text": "ok", "created_at": "2026-09-25T10:00:01Z"},
    ]})
    with nc.as_user(USER_ID):
        agent = nc.Agent.create("helper", instructions="Help.")
    assert create.calls.last.request.headers["NoClick-User"] == USER_ID
    reply = agent.message("hi", conversation="conv-1")
    assert reply.text == "ok"
    assert body(send.calls.last.request) == {"text": "hi", "conversation": "conv-1"}
    assert send.calls.last.request.headers["NoClick-User"] == USER_ID
    with nc.as_user("someone_else"):  # a user's own agent always acts for that user
        messages = agent.history("conv-1")
    assert [(m.role, m.text) for m in messages] == [("user", "hi"), ("assistant", "ok")]
    assert history.calls.last.request.headers["NoClick-User"] == USER_ID


def test_list_get_update_delete(api, client):
    lst = api.get("/v1/agents").respond(json=listing(AGENT))
    api.get("/v1/agents/agt_1").respond(json=AGENT)
    patch = api.patch("/v1/agents/agt_1").respond(json={**AGENT, "model": "claude-y"})
    delete = api.delete("/v1/agents/agt_1").respond(json=trashed("agent", "agt_1", "sunrise-host"))
    [agent] = nc.Agent.list(name="sunrise-host")
    assert lst.calls.last.request.url.params["name"] == "sunrise-host"
    same = nc.Agent.get("agt_1")
    assert same == agent and same.workflow_id == "wf_1"
    assert agent.update(model="claude-y").model == "claude-y"
    assert body(patch.calls.last.request) == {"model": "claude-y"}
    assert agent.delete().purge_after.month == 10
    assert delete.call_count == 1


APP_AGENT = {
    "object": "agent", "id": "node:wf_9:triage", "origin": "app", "name": "Triage", "harness": "sdk",
    "model": "openai/gpt-5", "instructions": "You sort the queue.", "workflow_id": "wf_9", "node_id": "triage",
    "workflow_name": "Support desk", "access": "owner", "enabled": True,
    "app_url": "https://noclick.com/dashboard?tab=workflows&workflow=wf_9", "created_at": "2026-09-25T10:00:00Z",
}


def test_an_agent_built_in_the_app_is_listed_and_messaged(api, client):
    lst = api.get("/v1/agents").respond(json=listing(APP_AGENT))
    send = api.post("/v1/agents/node:wf_9:triage/messages").respond(json=operation(
        op_id="op_w", kind="workflow.agent_message", status="running"))
    api.get("/v1/operations/op_w/wait").respond(json=operation(
        op_id="op_w", kind="workflow.agent_message", status="succeeded",
        result={"text": "Two tickets are urgent.", "conversation": "c_1"}))
    [triage] = nc.Agent.list(origin="app")
    assert lst.calls.last.request.url.params["origin"] == "app"
    assert (triage.origin, triage.workflow_name, triage.node_id, triage.access, triage.enabled, triage.app_url) == (
        "app", "Support desk", "triage", "owner", True, "https://noclick.com/dashboard?tab=workflows&workflow=wf_9")
    reply = triage.message("Anything urgent?")
    assert body(send.calls.last.request) == {"text": "Anything urgent?"}
    assert (reply.text, reply.conversation, reply.operation_id) == ("Two tickets are urgent.", "c_1", "op_w")
    with pytest.raises(ValueError):
        nc.Agent.list(origin="workflow")


def test_agent_message_failure_raises_typed_error(api, client):
    api.get("/v1/agents/agt_1").respond(json=AGENT)
    api.post("/v1/agents/agt_1/messages").respond(json=operation(
        op_id="op_m", kind="agent.message", status="failed",
        error={"type": "payment_required", "message": "Your account can't pay for this.", "next_step": "Add funds."}))
    with pytest.raises(nc.PaymentRequired):
        nc.Agent.from_id("agt_1").message("hi")


async def test_agent_message_aio(api, client):
    api.get("/v1/agents").respond(json=listing(AGENT))
    api.post("/v1/agents/agt_1/messages").respond(json=operation(
        op_id="op_m", kind="agent.message", status="succeeded", result={"text": "hello"}))
    reply = await nc.Agent.from_name("sunrise-host").message.aio("hi")
    assert reply.text == "hello"


def test_shared_human_follows_the_current_user(api, client):
    route = api.post("/v1/humans/requests").respond(json=operation(kind="human.notify", status="succeeded"))
    human = nc.Human()
    with nc.as_user("user_5"):
        human.notify("hi")
    assert route.calls.last.request.headers["NoClick-User"] == "user_5"


def test_shared_agent_talks_as_the_current_user(api, client):
    api.get("/v1/agents").respond(json=listing(AGENT))  # account-level (user_id None)
    send = api.post("/v1/agents/agt_1/messages").respond(json=operation(
        op_id="op_m", kind="agent.message", status="succeeded", result={"text": "hi", "conversation": "c1"}))
    history = api.get("/v1/agents/agt_1/conversations/c1").respond(json={"messages": []})
    agent = nc.Agent.from_name("sunrise-host")  # made outside any user
    for user in ("user_1", "user_2"):
        with nc.as_user(user):
            agent.message("hello")
            agent.history("c1")
        assert send.calls.last.request.headers["NoClick-User"] == user
        assert history.calls.last.request.headers["NoClick-User"] == user
    agent.message("hello", user="user_3")
    assert send.calls.last.request.headers["NoClick-User"] == "user_3"
    agent.message("hello")
    assert "NoClick-User" not in send.calls.last.request.headers


def test_grants_read_fresh_and_revoke_by_grant_or_id(api, client):
    grant = {"object": "agent_grant", "id": "gr_1", "connection": "work-gmail", "connection_id": "con_1",
             "integration": "gmail", "operations": ["send_email_message"], "status": "active",
             "reason": "To send your summary.", "conversation": "c1",
             "created_at": "2026-09-25T10:00:00Z", "granted_at": "2026-09-25T10:05:00Z"}
    read = api.get("/v1/agents/agt_1").respond(json={**AGENT, "grants": [grant]})
    revoke = api.delete("/v1/agents/agt_1/grants/gr_1").respond(json={"object": "agent_grant", "id": "gr_1",
                                                                       "revoked": True})
    agent = nc.Agent.from_id("agt_1")
    [got] = agent.grants()
    assert (got.connection, got.integration, got.operations, got.status) == (
        "work-gmail", "gmail", ["send_email_message"], "active")
    assert got.granted_at.minute == 5 and read.call_count == 2  # hydrate, then the fresh read
    agent.revoke_grant(got)
    agent.revoke_grant("gr_1")
    assert revoke.call_count == 2
