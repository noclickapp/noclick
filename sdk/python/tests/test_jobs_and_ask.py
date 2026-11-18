"""Spawn with the updates a parent requires, jobs and their updates, ask, and the
agents capability that does these from inside an agent: built."""

import asyncio
from datetime import timedelta

import pytest

import noclick as nc
from platform_helpers import USER_ID, agent_row, body, listing, operation

AGENT = agent_row(id="ag_1", name="planner")
USER_AGENT = agent_row(id="ag_u", name="assistant", user_id=USER_ID)
UPDATE = {
    "object": "job_update", "id": "up_1", "job_id": "op_t", "agent_id": "ag_k", "kind": "before",
    "text": "Refunding $95 for the cracked mug.", "tool": "stripe.create_refund", "arguments": {"amount": 9500},
    "status": "running", "result": None, "error": None, "waiting_on": None, "wakeup_id": "wk_9",
    "created_at": "2026-10-01T10:05:00Z",
}
JOB = operation("op_t", kind="agent.task", status="running", step="working", agent_id="ag_k", started_by="ag_1",
                conversation="task-ag_k", parent_conversation="launch-plan", updates=["done", "blocked"],
                latest_update=UPDATE)

# --- spawn, jobs and updates -------------------------------------------------------------

def test_spawn_starts_the_task_with_the_updates_its_parent_requires(api, client):
    api.get("/v1/agents/ag_1").respond(json={**AGENT, "tools": ["search", "fetch", "agents"]})
    api.get("/v1/connections/claude").respond(json={"object": "connection", "id": "cn_c", "name": "claude",
                                                    "integration": "anthropic", "status": "connected"})
    spawn = api.post("/v1/agents/ag_1/children").respond(201, json=agent_row(
        id="ag_k", name="researcher", parent_id="ag_1", job_id="op_t", job=JOB))
    child = nc.Agent.from_id("ag_1").spawn(
        "Find three recent launches.",
        instructions="Report each launch as you finish it.",
        tools=["search", "fetch"],
        updates=["blocked", nc.Before("gmail.send_email_message", "stripe.*"), nc.Every(timedelta(minutes=15)), "done"],
        conversation="launch-plan",
        budget_usd=0.5, ttl_s=3600, model="sonnet", harness="claude_code",
        model_connection=nc.Connection.from_name("claude"), name="researcher",
    )
    assert body(spawn.calls.last.request) == {
        "task": "Find three recent launches.",
        "updates": ["done", "blocked", {"before": ["gmail.send_email_message", "stripe.*"]}, {"every_s": 900}],
        "conversation": "launch-plan", "instructions": "Report each launch as you finish it.",
        "tools": ["search", "fetch"], "budget_usd_per_month": 0.5, "ttl_s": 3600, "model": "sonnet",
        "harness": "claude_code", "model_connection": "claude", "name": "researcher",
    }
    job = child.job
    assert isinstance(job, nc.Job) and (job.id, job.kind, job.step) == ("op_t", "agent.task", "working")
    assert (job.started_by, job.conversation, job.parent_conversation) == ("ag_1", "task-ag_k", "launch-plan")
    assert job.required_updates == ["done", "blocked"]
    assert job.latest_update.kind == "before" and job.latest_update.arguments == {"amount": 9500}
    assert isinstance(job.agent, nc.Agent) and job.agent.id == "ag_k"


def test_a_spawned_tasks_job_waits_for_its_reply(api, client):
    api.get("/v1/agents/ag_k").respond(json=agent_row(id="ag_k", job_id="op_t"))
    api.get("/v1/operations/op_t").respond(json=JOB)
    api.get("/v1/operations/op_t/wait").respond(json={**JOB, "status": "succeeded", "result": {
        "text": "Three launches: ...", "conversation": "task-ag_k", "tool_calls": []}})
    job = nc.Agent.from_id("ag_k").job
    reply = job.wait()
    assert isinstance(reply, nc.AgentReply) and reply.text == "Three launches: ..."


def test_an_agent_spawn_didnt_start_has_no_job(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    assert nc.Agent.from_id("ag_1").job is None


def test_updates_are_done_blocked_before_or_every():
    with pytest.raises(ValueError, match="'done', 'blocked'"):
        asyncio.run(nc.Agent.from_id("ag_1").spawn.aio("x", updates=["progress"]))
    with pytest.raises(ValueError, match="at least 60"):
        nc.Every(30)
    with pytest.raises(ValueError, match="whole number of seconds"):
        nc.Every(90.5)  # refused, never truncated
    with pytest.raises(TypeError, match="seconds or a timedelta"):
        nc.Every("15m")
    with pytest.raises(ValueError, match="at least one"):
        nc.Before()
    with pytest.raises(TypeError, match="patterns"):
        nc.Before("gmail.*", 42)
    assert nc.Every(timedelta(minutes=5)) == nc.Every(300) and nc.Every(300).interval_s == 300
    assert nc.Before("a.*").tools == ["a.*"] and repr(nc.Before("a.*")) == "Before('a.*')"


def test_jobs_read_what_an_agent_started(api, client):
    api.get("/v1/agents/ag_u").respond(json=USER_AGENT)
    rows = api.get("/v1/agents/ag_u/jobs").respond(json=listing(JOB, operation("op_m", kind="agent.message",
                                                                              status="succeeded", agent_id="ag_x")))
    task, message = nc.Agent.from_id("ag_u").jobs(status="live", kind=["task", "message"],
                                                  agent=nc.Agent.from_id("ag_k"), conversation="launch-plan")
    params = rows.calls.last.request.url.params
    assert (params["status"], params["kind"], params["agent_id"], params["conversation"]) == (
        "live", "agent.task,agent.message", "ag_k", "launch-plan")
    assert rows.calls.last.request.headers["NoClick-User"] == USER_ID
    assert isinstance(task, nc.Job) and isinstance(message, nc.Job) and message.kind == "agent.message"
    assert message.latest_update is None
    with pytest.raises(ValueError, match="'task' or 'message'"):
        nc.Agent.from_id("ag_u").jobs(kind="turn")


def test_job_list_reads_only_jobs(api, client):
    rows = api.get("/v1/operations").respond(json=listing(JOB))
    [job] = nc.Job.list(status="live", agent="ag_k")
    params = rows.calls.last.request.url.params
    # Job.list reads tasks: only agent.jobs() tells a coordinator's message jobs from other agent.messages.
    assert (params["kind"], params["status"], params["agent_id"]) == ("agent.task", "live", "ag_k")
    assert isinstance(job, nc.Job) and job.parent_conversation == "launch-plan"
    page = nc.Job.list_page(limit=5)
    assert isinstance(page.data[0], nc.Job) and rows.calls.last.request.url.params["limit"] == "5"
    with pytest.raises(TypeError, match="Job.list reads only agent.task operations"):
        nc.Job.list(kind="human.ask")
    summary = api.get("/v1/operations/summary").respond(json={"total": 2, "by_status": {"running": 2}})
    assert nc.Job.summary(status="live").total == 2
    assert summary.calls.last.request.url.params["kind"] == "agent.task"
    with pytest.raises(TypeError, match="Job.summary reads only"):
        nc.Job.summary(kind="agent.ask")


def test_a_jobs_updates_oldest_first(api, client):
    api.get("/v1/operations/op_t/updates").respond(json=listing(
        {**UPDATE, "id": "up_0", "kind": "blocked", "text": "Waiting for its user to connect Stripe ('stripe').",
         "tool": None, "arguments": None, "status": "awaiting_human",
         "waiting_on": {"kind": "connection", "url": "https://noclick.test/c/1", "operation_id": "op_c"}},
        UPDATE,
        {**UPDATE, "id": "up_2", "kind": "done", "status": "succeeded", "result": {"text": "Refunded."}, "tool": None},
    ))
    blocked, before, done = nc.Job.from_id("op_t").updates()
    assert isinstance(blocked, nc.JobUpdate) and blocked.waiting_on["kind"] == "connection"
    assert (before.tool, before.wakeup_id) == ("stripe.create_refund", "wk_9")
    assert done.result == {"text": "Refunded."} and done.created_at.minute == 5


# --- ask --------------------------------------------------------------------------------

def test_ask_answers_from_a_snapshot_or_joins_the_running_turn(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    ask = api.post("/v1/agents/ag_1/ask").respond(202, json=operation("op_a", kind="agent.ask", status="running"))
    api.get("/v1/operations/op_a/wait").respond(json=operation("op_a", kind="agent.ask", status="succeeded", result={
        "text": "Two of three launches done.", "conversation": "task-ag_k", "tool_calls": [], "joined": None}))
    reply = nc.Agent.from_id("ag_1").ask("Where are you?")
    assert body(ask.calls.last.request) == {"question": "Where are you?"}
    assert isinstance(reply, nc.AgentReply) and reply.text == "Two of three launches done."
    with nc.as_user(USER_ID):
        nc.Agent.from_id("ag_1").ask("Skip the e2e suite.", conversation="issue-1841", interject=True)
    assert body(ask.calls.last.request) == {"question": "Skip the e2e suite.", "conversation": "issue-1841",
                                            "interject": True}
    assert ask.calls.last.request.headers["NoClick-User"] == USER_ID


def test_interject_with_nothing_running_is_an_ordinary_message(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.post("/v1/agents/ag_1/ask").respond(202, json=operation("op_m", kind="agent.message", status="queued"))
    api.get("/v1/operations/op_m/wait").respond(json=operation("op_m", kind="agent.message", status="succeeded", result={
        "text": "Noted.", "conversation": "issue-1841", "tool_calls": []}))
    reply = nc.Agent.from_id("ag_1").ask("Skip the e2e suite.", conversation="issue-1841", interject=True)
    assert isinstance(reply, nc.AgentReply) and (reply.text, reply.operation_id) == ("Noted.", "op_m")


def test_a_plan_backed_agents_snapshot_is_not_available(api, client):
    api.get("/v1/agents/ag_1").respond(json=AGENT)
    api.post("/v1/agents/ag_1/ask").respond(409, json={"error": {
        "type": "not_available", "message": "This agent thinks with a Claude or ChatGPT plan, ...",
        "next_step": "Ask with interject=True to put the question into its running turn, or message it.",
        "reason": "plan_snapshot"}})
    with pytest.raises(nc.NotAvailable, match="plan"):
        nc.Agent.from_id("ag_1").ask("Status?", conversation="docs-1")


# --- the agents capability --------------------------------------------------------------------

def test_the_agents_capability_in_tools(api, client):
    create = api.post("/v1/agents").respond(json=AGENT)
    nc.Agent.create("coordinator", instructions="Run launches.", tools=["search", nc.Agents()])
    assert body(create.calls.last.request)["tools"] == ["search", "agents"]
    nc.Agent.create("watcher", instructions="Watch.", tools=nc.Agents.only("status", "list", "ask"))
    # Narrowed, one ref per tool in the capability's order, named as policy names them.
    assert body(create.calls.last.request)["tools"] == ["agents.ask", "agents.status", "agents.list"]
    assert nc.Agents.only("spawn") == nc.Agents.only("spawn") and repr(nc.Agents()) == "Agents()"
    # Every tool named (twice, here) is the whole capability, sent as "agents".
    nc.Agent.create("lead", instructions="Lead.", tools=[nc.Agents.only(*nc.Agents.TOOLS, "ask")])
    assert body(create.calls.last.request)["tools"] == ["agents"]
    with pytest.raises(ValueError, match="'spawn', 'message', 'ask', 'status', 'list', 'cancel'"):
        nc.Agents.only("delete")
    with pytest.raises(ValueError, match="at least one"):
        nc.Agents.only()
