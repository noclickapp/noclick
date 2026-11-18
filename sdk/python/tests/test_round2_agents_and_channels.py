import asyncio

import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID, body, listing, user_row

PARENT = {
    "object": "agent", "id": "agt_p", "name": "planner", "model": "openrouter/x", "harness": "sdk",
    "instructions": "Plan.", "tools": ["gmail"], "user_id": USER_ID, "workflow_id": "wf_p",
    "parent_id": None, "ttl_s": None, "expires_at": None, "budget_usd_per_month": 20.0,
    "created_at": "2026-09-25T10:00:00Z",
}


def _agent(agent_id, name, **extra):
    return {**PARENT, "id": agent_id, "name": name, **extra}


# --- agents ----------------------------------------------------------------------

def test_create_with_tools_ttl_parent_and_budget(api, client):
    api.get("/v1/agents").respond(json=listing(PARENT))
    create = api.post("/v1/agents").respond(json=_agent("agt_c", "helper", parent_id="agt_p", ttl_s=600,
                                                         expires_at="2026-09-25T10:10:00Z"))
    api.get("/v1/connections/slack").respond(404, json={"error": {"type": "not_found", "message": "No"}})
    made = api.post("/v1/connections").respond(201, json={
        "object": "connection", "id": "con_s", "name": "slack", "integration": "slack", "user_id": USER_ID,
        "status": "pending", "connect_link": None})
    with nc.as_user(USER_ID):
        parent = nc.Agent.from_name("planner")  # lazy: resolved when the child is created
        slack = nc.Connection.from_name("slack", integration="slack", create_if_missing=True)  # created first
        child = nc.Agent.create("helper", instructions="Help.", tools=["gmail.send_email", slack],
                                ttl_s=600, parent_id=parent, budget_usd_per_month=3)
    assert made.call_count == 1 and made.calls.last.request.headers["NoClick-User"] == USER_ID
    with pytest.raises(TypeError):
        nc.Agent.create("helper", instructions="Help.", tools=[nc.IntegrationInfo("slack", "Slack", "app", False, ["oauth"], 1, 0, [], {})])
    assert body(create.calls.last.request) == {
        "name": "helper", "instructions": "Help.", "tools": ["gmail.send_email", "slack"],
        "ttl_s": 600, "parent_id": "agt_p", "budget_usd_per_month": 3,
    }
    assert (child.parent_id, child.ttl_s) == ("agt_p", 600) and child.expires_at.minute == 10


def test_from_name_create_if_missing_resolves_parent_on_first_use(api, client):
    api.get("/v1/agents").mock(side_effect=[
        httpx.Response(200, json=listing()),        # looking up "helper"
    ])
    api.get("/v1/agents/agt_p").respond(json=PARENT)
    create = api.post("/v1/agents").respond(json=_agent("agt_c", "helper", parent_id="agt_p"))
    agent = nc.Agent.from_name("helper", create_if_missing=True, instructions="Help.", tools="gmail",
                               parent_id=nc.Agent.from_id("agt_p"), ttl_s=60)
    assert create.call_count == 0
    assert agent.id == "agt_c"
    assert body(create.calls.last.request) == {
        "name": "helper", "instructions": "Help.", "tools": ["gmail"], "ttl_s": 60, "parent_id": "agt_p",
    }


# spawn is designed now: its first argument is the task, started at once under the parent's children route.

def test_from_name_never_finds_an_expired_agent(api, client):
    """An expired agent gave its name up: ``from_name`` creates a new one, or finds none."""
    api.get("/v1/agents").respond(json=listing(_agent("agt_old", "helper", status="expired")))
    create = api.post("/v1/agents").respond(json=_agent("agt_new", "helper"))
    with nc.as_user(USER_ID):
        helper = nc.Agent.from_name("helper", create_if_missing=True, instructions="Help.")
        assert helper.id == "agt_new" and create.call_count == 1
        with pytest.raises(nc.NotFound):
            nc.Agent.from_name("helper").id


def test_an_account_agents_activity_is_none_for_a_user_and_ttl_s_reads_back(api, client):
    """A user's call reads an account agent without its activity, which other users' turns move."""
    shared = _agent("agt_s", "shared", user_id=None, ttl_s=900, expires_at="2026-09-25T10:15:00Z", status=None,
                    last_active_at=None, running_turns=None, child_count=None)
    api.get("/v1/agents/agt_s").respond(json=shared)
    with nc.as_user(USER_ID):
        agent = nc.Agent.get("agt_s")
    assert (agent.status, agent.last_active_at, agent.running_turns, agent.child_count) == (None, None, None, None)
    assert agent.ttl_s == 900


def test_spawn_creates_a_child_where_the_parent_lives(api, client):
    api.get("/v1/agents/agt_p").respond(json=PARENT)
    create = api.post("/v1/agents/agt_p/children").respond(201, json=_agent(
        "agt_k", "planner-kid", parent_id="agt_p",
        job={"object": "operation", "id": "op_t", "kind": "agent.task", "status": "running", "agent_id": "agt_k"}))
    parent = nc.Agent.get("agt_p")
    child = parent.spawn("Summarize the inbox.", tools=["gmail.list_emails"], ttl_s=900, budget_usd=0.5)
    # The server names the child and gives it the parent's model and harness when the call doesn't.
    assert body(create.calls.last.request) == {
        "task": "Summarize the inbox.", "updates": ["done"], "tools": ["gmail.list_emails"], "ttl_s": 900,
        "budget_usd_per_month": 0.5,
    }
    assert create.calls.last.request.headers["NoClick-User"] == USER_ID
    assert isinstance(child, nc.Agent) and child.parent_id == "agt_p"
    assert isinstance(child.job, nc.Job) and child.job.kind == "agent.task"
    parent.spawn("x", name="named", model="openrouter/y")
    assert body(create.calls.last.request)["name"] == "named"
    assert body(create.calls.last.request)["model"] == "openrouter/y"
    assert "tools" not in body(create.calls.last.request)


def test_spawn_from_an_account_agent_stays_account_level(api, client):
    api.get("/v1/agents/agt_a").respond(json=_agent("agt_a", "host", user_id=None))
    create = api.post("/v1/agents/agt_a/children").respond(201, json=_agent("agt_k", "host-kid", user_id=None))
    nc.Agent.from_id("agt_a").spawn("sub-task")
    assert "NoClick-User" not in create.calls.last.request.headers
    # Inside as_user, the header names whose conversation the updates wake, as message() does.
    with nc.as_user("user_1"):
        child = nc.Agent.from_id("agt_a").spawn("sub-task", conversation="launch")
    assert create.calls.last.request.headers["NoClick-User"] == "user_1"
    assert body(create.calls.last.request) == {"task": "sub-task", "updates": ["done"], "conversation": "launch"}
    assert child.user_id is None


def test_a2a_card_and_url(api, client):
    api.get("/v1/agents/agt_p").respond(json=PARENT)
    card = api.get("/v1/agents/agt_p/a2a/card").respond(json={"name": "planner", "skills": []})
    agent = nc.Agent.from_id("agt_p")
    assert agent.a2a_card() == {"name": "planner", "skills": []}
    assert card.calls.last.request.headers["NoClick-User"] == USER_ID
    assert agent.a2a_url == "https://api.test/v1/agents/agt_p/a2a"
    served = nc.Agent.get("agt_p")
    served._raw["a2a_url"] = "https://a2a.example.com/agt_p"
    assert served.a2a_url == "https://a2a.example.com/agt_p"


def test_update_budget(api, client):
    api.get("/v1/agents/agt_p").respond(json=PARENT)
    patch = api.patch("/v1/agents/agt_p").respond(json={**PARENT, "budget_usd_per_month": 50})
    assert nc.Agent.from_id("agt_p").update(budget_usd_per_month=50).budget_usd_per_month == 50
    assert body(patch.calls.last.request) == {"budget_usd_per_month": 50}


def test_concurrent_turn_is_a_conflict(api, client):
    api.get("/v1/agents/agt_p").respond(json=PARENT)
    api.post("/v1/agents/agt_p/messages").respond(409, json={"error": {
        "type": "conflict", "message": "A turn is already running in this conversation.",
        "next_step": "Wait for it to finish, then send again."}})
    with pytest.raises(nc.Conflict):
        nc.Agent.from_id("agt_p").message("hi", conversation="c1")


# --- harnesses ---------------------------------------------------------------------

CLAUDE = {
    "object": "connection", "id": "con_cl", "name": "claude", "integration": "anthropic",
    "credential_type": "agent_anthropic", "user_id": None, "status": "pending",
    "connect_link": {"id": "lnk_c", "url": "https://noclick.com/c/claude", "expires_at": "2026-10-02T10:00:00Z",
                     "operation_id": "op_c"},
}
CODER = _agent("agt_cc", "coder", user_id=None, harness="claude_code", model="sonnet", model_connection="claude")
HARNESSES = listing(
    {"object": "harness", "name": "sdk", "label": "NoClick", "version": None,
     "default_model": "openrouter/~openai/gpt-luna-latest", "custom_models": True,
     "model_connection": "optional", "integrations": ["openrouter", "anthropic", "openai"], "streaming": "tokens",
     "shell": "code_capability", "notes": ["Streams its reply; code, search and fetch are tools you list."]},
    {"object": "harness", "name": "codex", "label": "Codex", "version": "0.156.1", "default_model": "gpt-5.6-luna",
     "custom_models": True, "model_connection": "required", "integrations": ["openai"], "streaming": "final",
     "shell": "built_in", "notes": ["On a ChatGPT API key, codex shows tools only to codex-family models such as gpt-5-codex."]},
)
CODEX_MODELS = listing({"object": "harness_model", "id": "gpt-5.6-luna", "label": "gpt-5.6-luna", "canonical": "gpt-5.6-luna",
                        "route": "maker", "noclick_key": {"output_usd_per_million": 40, "needs_funds_usd": 5}},
                       {"object": "harness_model", "id": "openrouter/openai/gpt-5-codex", "label": None,
                        "canonical": "openai/gpt-5-codex", "route": "openrouter", "noclick_key": None})


def test_harnesses_read_the_catalog_for_no_user(api, client):
    route = api.get("/v1/harnesses").respond(json=HARNESSES)
    with nc.as_user(USER_ID):
        sdk, codex = nc.Agent.harnesses()
    assert "NoClick-User" not in route.calls.last.request.headers
    assert isinstance(codex, nc.HarnessInfo)
    assert (sdk.name, sdk.label, sdk.version, sdk.model_connection, sdk.streaming, sdk.shell) == (
        "sdk", "NoClick", None, "optional", "tokens", "code_capability")
    assert (codex.label, codex.version, codex.default_model, codex.custom_models) == ("Codex", "0.156.1", "gpt-5.6-luna", True)
    assert (codex.model_connection, codex.integrations, codex.streaming, codex.shell) == (
        "required", ["openai"], "final", "built_in")
    assert codex.notes == ["On a ChatGPT API key, codex shows tools only to codex-family models such as gpt-5-codex."]


def test_a_harness_searches_its_models_for_no_user_through_its_own_client(api, client):
    api.get("/v1/harnesses").respond(json=HARNESSES)
    models = api.get("/v1/harnesses/codex/models").respond(json=CODEX_MODELS)
    [codex] = [h for h in nc.Agent.harnesses() if h.name == "codex"]
    with nc.as_user(USER_ID):
        found = codex.models(search="gpt-5", limit=2)
    request = models.calls.last.request
    assert dict(request.url.params) == {"q": "gpt-5", "limit": "2"} and "NoClick-User" not in request.headers
    assert all(isinstance(m, nc.HarnessModel) for m in found)
    # Each says how it's reached, the model it is, and what it costs on NoClick's key.
    assert [(m.id, m.label, m.route, m.canonical, m.noclick_key) for m in found] == [
        ("gpt-5.6-luna", "gpt-5.6-luna", "maker", "gpt-5.6-luna",
         {"output_usd_per_million": 40, "needs_funds_usd": 5}),
        ("openrouter/openai/gpt-5-codex", None, "openrouter", "openai/gpt-5-codex", None)]
    assert asyncio.run(codex.models.aio())[0].id == "gpt-5.6-luna"
    assert dict(models.calls.last.request.url.params) == {"limit": "50"}

    # A harness read through another client searches through that client, not the default.
    other = nc.Client(api_key="nk_live_other", base_url=client.base_url, max_retries=0)
    [codex] = [h for h in nc.Agent.harnesses(client=other) if h.name == "codex"]
    codex.models()
    assert models.calls.last.request.headers["Authorization"] == "Bearer nk_live_other"
    assert "_client" not in repr(codex) and codex == nc.Agent.harnesses()[1]


def test_a_cli_agent_creates_its_lazy_model_connection_first_and_sends_its_name(api, client):
    api.get("/v1/agents").respond(json=listing())
    api.get("/v1/connections/claude").respond(404, json={"error": {"type": "not_found", "message": "No"}})
    made = api.post("/v1/connections").respond(201, json=CLAUDE)
    create = api.post("/v1/agents").respond(201, json=CODER)
    claude = nc.Connection.from_name("claude", integration="anthropic", create_if_missing=True)
    coder = nc.Agent.from_name("coder", create_if_missing=True, instructions="Plan.", harness="claude_code",
                               model="sonnet", model_connection=claude)
    assert (coder.harness, coder.model, coder.model_connection) == ("claude_code", "sonnet", "claude")
    assert body(made.calls.last.request) == {"name": "claude", "integration": "anthropic"}
    assert body(create.calls.last.request) == {
        "name": "coder", "instructions": "Plan.", "model": "sonnet", "harness": "claude_code",
        "model_connection": "claude",
    }
    # A name is sent as it is; a connection from another scope is named by id (refused like a tool).
    nc.Agent.create("coder2", instructions="Plan.", harness="codex", model_connection="openai")
    assert body(create.calls.last.request)["model_connection"] == "openai"
    with nc.as_user(USER_ID):
        nc.Agent.create("mine", instructions="Plan.", harness="claude_code", model_connection=claude)
    assert body(create.calls.last.request)["model_connection"] == "connection:con_cl"
    with pytest.raises(TypeError):
        nc.Agent.create("x", instructions="Plan.", harness="codex", model_connection=42)


def test_from_name_converges_harness_and_model_connection_without_resending_the_model(api, client):
    api.get("/v1/agents").respond(json=listing({**CODER, "instructions": "Plan."}))
    patch = api.patch("/v1/agents/agt_cc").respond(json={
        **CODER, "instructions": "Plan.", "harness": "codex", "model": "gpt-5.6-luna", "model_connection": "openai"})
    same = nc.Agent.from_name("coder", create_if_missing=True, instructions="Plan.", harness="claude_code",
                              model_connection="claude")
    assert same.id == "agt_cc" and patch.call_count == 0
    moved = nc.Agent.from_name("coder", create_if_missing=True, instructions="Plan.", harness="codex",
                               model_connection="openai")
    assert (moved.harness, moved.model) == ("codex", "gpt-5.6-luna")
    # The server gives a new harness its default model, so the next run of this code sends nothing.
    assert body(patch.calls.last.request) == {"harness": "codex", "model_connection": "openai"}


def test_update_sets_or_removes_the_model_connection(api, client):
    api.get("/v1/agents/agt_cc").respond(json=CODER)
    patch = api.patch("/v1/agents/agt_cc").respond(json={**CODER, "harness": "sdk", "model_connection": None})
    api.get("/v1/connections/con_o").respond(json={**CLAUDE, "id": "con_o", "name": "openai"})
    agent = nc.Agent.from_id("agt_cc")
    agent.update(harness="codex", model_connection=nc.Connection.from_id("con_o"))
    assert body(patch.calls.last.request) == {"harness": "codex", "model_connection": "openai"}
    agent.update(harness="sdk", model_connection=None)
    assert body(patch.calls.last.request) == {"harness": "sdk", "model_connection": None}
    assert agent.model_connection is None


def test_spawn_leaves_the_parents_harness_and_model_connection_to_the_server(api, client):
    api.get("/v1/agents/agt_cc").respond(json=CODER)
    create = api.post("/v1/agents/agt_cc/children").respond(201, json=_agent(
        "agt_k", "coder-kid", parent_id="agt_cc", harness="claude_code", model="sonnet", model_connection="claude"))
    kid = nc.Agent.from_id("agt_cc").spawn("Fix the links.", name="kid")
    # Nothing about the harness is sent: the child runs on its parent's unless the call says otherwise.
    assert body(create.calls.last.request) == {"task": "Fix the links.", "updates": ["done"], "name": "kid"}
    assert (kid.harness, kid.model, kid.model_connection) == ("claude_code", "sonnet", "claude")
    nc.Agent.from_id("agt_cc").spawn("Port it.", harness="codex", model_connection="openai")
    assert body(create.calls.last.request) == {
        "task": "Port it.", "updates": ["done"], "harness": "codex", "model_connection": "openai",
    }


def test_a_cli_turn_reports_its_step_until_the_reply_lands(api, client):
    api.get("/v1/agents/agt_cc").respond(json=CODER)
    api.post("/v1/agents/agt_cc/messages").respond(202, json=operation_view("queued"))
    api.get("/v1/operations/op_m").mock(side_effect=[
        httpx.Response(200, json=operation_view("running", step="delivering")),
        httpx.Response(200, json=operation_view("running", step="working")),
    ])
    api.get("/v1/operations/op_m/wait").respond(json=operation_view("succeeded", result={
        "text": "Fixed 3 links.", "conversation": "docs-1", "cost_usd": 0.04,
        "tool_calls": [{"tool": "Bash", "source": "harness", "is_error": False}]}))
    turn = nc.Agent.from_id("agt_cc").send("Fix the links", conversation="docs-1")
    assert turn.step is None
    assert (turn.refresh().status, turn.step) == ("running", "delivering")
    assert turn.refresh().step == "working"
    reply = turn.wait()
    assert (reply.text, reply.tool_calls[0]["source"]) == ("Fixed 3 links.", "harness")
    assert turn.step is None


def operation_view(status, step=None, result=None):
    return {"object": "operation", "id": "op_m", "kind": "agent.message", "status": status, "step": step,
            "result": result, "error": None, "created_at": "2026-09-25T10:00:00Z",
            "updated_at": "2026-09-25T10:00:00Z"}


# --- channels --------------------------------------------------------------------

CHANNEL = {
    "object": "channel", "id": "ch_1", "name": "launch", "mode": "mentions", "status": "open",
    "max_agent_turns": 20, "budget_usd": 2.0, "user_id": USER_ID, "created_at": "2026-09-25T10:00:00Z",
    "members": [
        {"id": "mem_1", "type": "agent", "agent_id": "agt_p", "name": "planner"},
        {"id": "mem_2", "type": "user", "user_id": USER_ID, "name": "Ana"},
        {"id": "mem_3", "type": "a2a", "a2a_url": "https://remote.ai/a2a", "name": "remote"},
    ],
}


def _message(message_id, text, author=("agent", "agt_p", "planner")):
    return {"object": "channel_message", "id": message_id, "channel_id": "ch_1",
            "author": dict(zip(("type", "id", "name"), author)), "text": text, "mentions": [],
            "created_at": "2026-09-25T10:00:00Z"}


def test_create_with_agent_user_and_a2a_members(api, client):
    api.get(f"/v1/users/{USER_ID}").respond(json=user_row())
    api.get("/v1/agents/agt_p").respond(json=PARENT)
    create = api.post("/v1/channels").respond(json=CHANNEL)
    user = nc.User.get(USER_ID)
    channel = nc.Channel.create("launch", members=[nc.Agent.from_id("agt_p"), user, "https://remote.ai/a2a"],
                                mode="mentions", max_agent_turns=20, max_mention_hops=4, budget_usd=2)
    assert body(create.calls.last.request) == {
        "name": "launch", "members": [{"agent_id": "agt_p"}, {"user": True}, {"a2a_url": "https://remote.ai/a2a"}],
        "mode": "mentions", "max_agent_turns": 20, "max_mention_hops": 4, "budget_usd": 2,
    }
    assert create.calls.last.request.headers["NoClick-User"] == USER_ID
    assert [(m.id, m.type) for m in channel.members] == [("mem_1", "agent"), ("mem_2", "user"), ("mem_3", "a2a")]
    assert channel.members[2].a2a_url == "https://remote.ai/a2a"


def test_create_validates_mode_members_and_users(api, client):
    with pytest.raises(ValueError, match="mode"):
        nc.Channel.create("x", mode="loud")
    with pytest.raises(TypeError, match="channel member"):
        nc.Channel.create("x", members=["planner"])
    a, b = nc.User.from_id(USER_ID), nc.User.from_id("t2")
    with pytest.raises(ValueError, match="one user"):
        nc.Channel.create("x", members=[a, b])
    with pytest.raises(ValueError, match="one user"):
        nc.Channel.create("x", members=[a], user="user_9")


def test_create_leaves_the_mode_to_the_server_whose_default_wakes_every_agent(api, client):
    """Left out, ``mode`` isn't sent: the server opens the room ``all``, a person's message waking every agent."""
    create = api.post("/v1/channels").respond(json={**CHANNEL, "mode": "all"})
    channel = nc.Channel.create("launch")
    assert "mode" not in body(create.calls.last.request)
    assert channel.mode == "all"


def test_list_pages_a_limit_over_the_servers_page_size(api, client):
    pages = []

    def serve(request):
        size, cursor = int(request.url.params["limit"]), request.url.params.get("cursor")
        assert size <= 100  # the server refuses a larger page
        pages.append((size, cursor))
        start = int(cursor or 0)
        rows = [{**CHANNEL, "id": f"ch_{i}"} for i in range(start, start + size)]
        return httpx.Response(200, json=listing(*rows, next_cursor=str(start + size)))

    api.get("/v1/channels").mock(side_effect=serve)
    channels = nc.Channel.list(limit=150)
    assert pages == [(100, None), (50, "100")]
    assert [c.id for c in channels] == [f"ch_{i}" for i in range(150)]


def test_post_as_agent_or_user(api, client):
    api.get("/v1/channels/ch_1").respond(json=CHANNEL)
    post = api.post("/v1/channels/ch_1/messages").respond(json=_message("m1", "@planner draft it",
                                                                        author=("user", USER_ID, "Ana")))
    channel = nc.Channel.get("ch_1")
    message = channel.post("@planner draft it", as_="user")
    assert body(post.calls.last.request) == {"text": "@planner draft it", "as": {"user": True}}
    assert post.calls.last.request.headers["NoClick-User"] == USER_ID  # the channel's user
    assert (message.author.type, message.author.name, str(message)) == ("user", "Ana", "@planner draft it")
    channel.post("on it", as_=nc.Agent.from_id("agt_p"))  # a lazy agent's id comes from its hints
    assert body(post.calls.last.request)["as"] == {"agent_id": "agt_p"}
    channel.post("from the account")
    assert body(post.calls.last.request) == {"text": "from the account"}
    with pytest.raises(TypeError):
        channel.post("x", as_="planner")


def test_messages_after_a_message(api, client):
    route = api.get("/v1/channels/ch_1/messages").respond(json=listing(_message("m2", "b"), _message("m3", "c")))
    channel = nc.Channel.from_id("ch_1")
    first = nc.ChannelMessage._from(_message("m1", "a"))
    messages = channel.messages(after=first, wait_s=5)
    assert [m.id for m in messages] == ["m2", "m3"]
    params = route.calls.last.request.url.params
    assert (params["after"], params["wait_s"]) == ("m1", "5")
    channel.messages()
    assert "after" not in route.calls.last.request.url.params


def test_stream_long_polls_until_closed(api, client):
    polls = api.get("/v1/channels/ch_1/messages").mock(side_effect=[
        httpx.Response(200, json=listing(_message("m1", "hi"), _message("m2", "hello"))),
        httpx.Response(200, json=listing(_message("m3", "done"))),
        httpx.Response(200, json=listing()),
    ])
    api.get("/v1/channels/ch_1").respond(json={**CHANNEL, "status": "closed"})
    texts = [m.text for m in nc.Channel.from_id("ch_1").stream(wait_s=10)]
    assert texts == ["hi", "hello", "done"]
    afters = [call.request.url.params.get("after") for call in polls.calls]
    assert afters == [None, "m2", "m3"]
    assert all(call.request.url.params["wait_s"] == "10" for call in polls.calls)


async def test_stream_aio_is_an_async_iterator(api, client):
    api.get("/v1/channels/ch_1/messages").mock(side_effect=[
        httpx.Response(200, json=listing(_message("m5", "x"))),
        httpx.Response(200, json=listing()),
    ])
    api.get("/v1/channels/ch_1").respond(json={**CHANNEL, "status": "closed"})
    channel = nc.Channel.from_id("ch_1")
    seen = [m.id async for m in channel.stream.aio(after="m4")]
    assert seen == ["m5"]


def test_stream_can_be_abandoned(api, client):
    api.get("/v1/channels/ch_1/messages").respond(json=listing(_message("m1", "a"), _message("m2", "b")))
    stream = nc.Channel.from_id("ch_1").stream()
    assert next(stream).id == "m1"
    stream.close()  # breaking out closes the generator on the SDK loop


def test_add_remove_and_close(api, client):
    api.get("/v1/channels/ch_1").respond(json=CHANNEL)
    add = api.post("/v1/channels/ch_1/members").respond(json={
        "id": "mem_4", "type": "agent", "agent_id": "agt_k", "name": "kid"})
    remove = api.delete(url__regex=r"/v1/channels/ch_1/members/mem_\d+").respond(204)
    close = api.post("/v1/channels/ch_1/close").respond(json={**CHANNEL, "status": "closed"})
    channel = nc.Channel.get("ch_1")
    member = channel.add(nc.Agent.from_id("agt_k"))
    assert member.id == "mem_4" and body(add.calls.last.request) == {"agent_id": "agt_k"}
    assert [m.id for m in channel.members][-1] == "mem_4"
    channel.remove(member)
    assert remove.calls.last.request.url.path.endswith("/mem_4")
    channel.remove("https://remote.ai/a2a")  # found by what you added
    assert remove.calls.last.request.url.path.endswith("/mem_3")
    channel.remove("mem_1")
    assert remove.calls.last.request.url.path.endswith("/mem_1")
    with pytest.raises(ValueError, match="not a member"):
        channel.remove(nc.Agent.from_id("agt_nobody"))
    assert channel.close().status == "closed" and close.call_count == 1


def test_add_accepts_a_channel_response(api, client):
    api.get("/v1/channels/ch_1").respond(json=CHANNEL)
    extra = {"id": "mem_9", "type": "a2a", "a2a_url": "https://x.ai/a2a"}
    api.post("/v1/channels/ch_1/members").respond(json={**CHANNEL, "members": [*CHANNEL["members"], extra]})
    member = nc.Channel.get("ch_1").add("https://x.ai/a2a")
    assert member.id == "mem_9"


def test_channel_context_manager_closes(api, client):
    api.post("/v1/channels").respond(json=CHANNEL)
    close = api.post("/v1/channels/ch_1/close").respond(json={**CHANNEL, "status": "closed"})
    with nc.Channel.create("launch") as channel:
        assert channel.status == "open"
    assert close.call_count == 1 and channel.status == "closed"

    async def use_async():
        async with nc.Channel.from_id("ch_1") as room:
            room._raw = dict(CHANNEL)
    asyncio.run(use_async())
    assert close.call_count == 2
