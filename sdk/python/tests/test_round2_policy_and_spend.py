import json

import httpx
import pytest
import respx

import noclick as nc
from platform_helpers import USER_ID, body, operation

APPROVAL_OP = operation(op_id="op_ap", kind="human.approve")


def _approval_required(op=APPROVAL_OP):
    return {"error": {
        "type": "approval_required", "message": "Sending email needs approval.",
        "next_step": "Wait for the approval, then retry with approval_id.",
        "approval_id": "ap_9", "request_id": "hr_9", "approve_url": "https://noclick.com/h/hr_9", "operation": op,
    }}


# --- spend caps ----------------------------------------------------------------

def test_spend_cap_exceeded_carries_cap_spent_scope(api, client):
    api.post("/v1/connections/gmail/operations/send_email/run").respond(402, json={"error": {
        "type": "spend_cap_exceeded", "message": "User spend cap reached.",
        "next_step": "Raise the user's spend_cap_usd_per_month.", "cap": 5.0, "spent": 5.02, "scope": "user",
    }})
    with pytest.raises(nc.SpendCapExceeded) as info:
        nc.Connection.from_name("gmail").run("send_email", {"to": "a@b.c"})
    err = info.value
    assert (err.cap, err.spent, err.scope, err.status) == (5.0, 5.02, "user", 402)
    assert "Raise the user" in str(err)


def test_spend_cap_on_a_failed_agent_turn(api, client):
    api.get("/v1/agents/agt_1").respond(json={"object": "agent", "id": "agt_1", "name": "a", "user_id": None})
    api.post("/v1/agents/agt_1/messages").respond(json=operation(
        op_id="op_m", kind="agent.message", status="failed",
        error={"type": "spend_cap_exceeded", "message": "Agent budget spent.", "cap": 1, "spent": 1, "scope": "agent"},
    ))
    with pytest.raises(nc.SpendCapExceeded) as info:
        nc.Agent.from_id("agt_1").message("hi")
    assert info.value.scope == "agent" and info.value.operation_id == "op_m"


# --- approvals -------------------------------------------------------------------

def test_approval_required_waits_then_retries_with_approval_id(api, client):
    run = api.post("/v1/connections/gmail/operations/send_email/run").mock(side_effect=[
        httpx.Response(402, json=_approval_required()),
        httpx.Response(200, json={"object": "operation_result", "result": {"id": "msg_1"}}),
    ])
    wait = api.get("/v1/operations/op_ap/wait").respond(json=operation(
        op_id="op_ap", kind="human.approve", status="succeeded", result={"approved": True, "text": "ok"}))
    with nc.as_user("user_42"):
        gmail = nc.Connection.from_name("gmail")
        with pytest.raises(nc.ApprovalRequired) as info:
            gmail.run("send_email", {"to": "a@b.c"})
    pending = info.value
    assert pending.approval_id == "ap_9" and pending.approve_url.endswith("/h/hr_9")
    approval = pending.operation
    assert isinstance(approval, nc.HumanRequest) and approval is pending.operation  # cached
    assert approval.url == pending.approve_url and approval.status == "awaiting_human"
    assert approval.request_id == "hr_9"  # the request a person answers, not the policy approval
    answered = api.post("/v1/humans/requests/hr_9/answer").respond(json={
        "object": "human_request", "id": "hr_9", "kind": "approve", "status": "answered"})
    approval.approve()
    assert body(answered.calls.last.request) == {"approved": True}
    assert answered.calls.last.request.headers["NoClick-User"] == "user_42"
    assert approval.wait() is True
    # the approval is polled for the user the refused call acted for
    assert wait.calls.last.request.headers["NoClick-User"] == "user_42"
    assert gmail.run("send_email", {"to": "a@b.c"}, approval_id=pending.approval_id) == {"id": "msg_1"}
    assert body(run.calls.last.request) == {"arguments": {"to": "a@b.c"}, "approval_id": "ap_9"}
    assert "approval_id" not in body(run.calls[0].request)


def test_an_approval_the_owner_answers_for_a_users_call_is_waited_on_as_the_account(api, client):
    """Acting for a user, a call the account's owner approves comes back with the account's approval
    (no user, no link): it's waited on without the user header, as the account key reads it."""
    api.post("/v1/connections/gmail/operations/send_email/run").respond(402, json={"error": {
        "type": "approval_required", "message": "Needs the owner's approval.", "next_step": "Wait, then retry.",
        "approval_id": "ap_7", "approver": "owner",
        "operation": operation(op_id="op_own", kind="human.approve", user_id=None)}})
    wait = api.get("/v1/operations/op_own/wait").respond(json=operation(
        op_id="op_own", kind="human.approve", status="succeeded", result={"approved": True}, user_id=None))
    with nc.as_user("user_42"):
        with pytest.raises(nc.ApprovalRequired) as info:
            nc.Connection.from_name("gmail").run("send_email", {"to": "a@b.c"})
        assert info.value.approve_url is None and info.value.operation.wait() is True
    assert "NoClick-User" not in wait.calls.last.request.headers


def test_approval_operation_as_bare_id_uses_the_raising_client(client):
    other = nc.Client(api_key="nk_live_other", base_url="https://other.test", max_retries=0)
    with respx.mock(base_url="https://other.test") as router:
        router.post("/v1/toolkits/call").respond(402, json=_approval_required(op="op_x"))
        wait = router.get("/v1/operations/op_x/wait").respond(json=operation(
            op_id="op_x", kind="human.approve", status="succeeded", result={"approved": False}))
        with pytest.raises(nc.ApprovalRequired) as info:
            nc.Toolkit(["gmail"], client=other).call("gmail__send_email", {"to": "a@b.c"})
        assert info.value.operation.wait() is False  # kind comes from the error, not the id
        assert wait.calls.last.request.headers["Authorization"] == "Bearer nk_live_other"


def _held_for_the_owner():
    """What the gate answers for a call it holds for the account's owner: the held call's id, never a request's."""
    return {"error": {
        "type": "approval_required",
        "message": "Send an email from 'gmail': it waits for the account's owner, who approves it from the link "
                   "NoClick sent them (by email).",
        "next_step": "Tell them to tap the link NoClick sent them; it runs once they approve.",
        "status": "awaiting_approval", "approval_id": "ap_h", "operation_id": "op_held",
        "summary": "Send an email from 'gmail'", "price": None, "expires_at": "2026-10-31T10:00:00Z",
        "accepting": None, "sent_to": ["email"]}}


def test_a_call_held_for_the_owner_waits_on_the_held_call_itself(api, client):
    run = api.post("/v1/connections/gmail/operations/send_email/run").respond(402, json=_held_for_the_owner())
    wait = api.get("/v1/operations/op_held/wait").respond(json=operation(
        op_id="op_held", kind="gate.held_call", status="succeeded",
        result={"status": 200, "response": {"object": "operation_result", "result": {"id": "msg_1"}}}))
    with nc.as_user("user_42"):
        with pytest.raises(nc.ApprovalRequired) as info:
            nc.Connection.from_name("gmail").run("send_email", {"to": "a@b.c"})
    held = info.value
    assert (held.approval_id, held.operation_id, held.sent_to) == ("ap_h", "op_held", ["email"])
    call = held.operation
    assert isinstance(call, nc.Operation) and not isinstance(call, nc.HumanRequest) and call is held.operation
    assert (call.id, call.kind) == ("op_held", "gate.held_call")
    # NoClick makes the call once the owner approves: its answer is the held call's result, nothing is retried.
    assert call.wait() == {"status": 200, "response": {"object": "operation_result", "result": {"id": "msg_1"}}}
    assert wait.calls.last.request.headers["NoClick-User"] == "user_42" and run.call_count == 1


def test_a_held_call_the_owner_declines_raises_from_its_wait(api, client):
    api.post("/v1/connections/gmail/operations/send_email/run").respond(402, json=_held_for_the_owner())
    api.get("/v1/operations/op_held/wait").respond(json=operation(
        op_id="op_held", kind="gate.held_call", status="failed",
        error={"type": "policy_denied", "message": "The person declined it."}))
    with pytest.raises(nc.ApprovalRequired) as info:
        nc.Connection.from_name("gmail").run("send_email", {"to": "a@b.c"})
    with pytest.raises(nc.PolicyDenied, match="declined"):
        info.value.operation.wait()


def test_approval_required_without_operation():
    err = nc.ApprovalRequired("m", details={"approval_id": "ap_1"})
    assert err.operation is None and err.approval_id == "ap_1"


def test_toolkit_call_sends_approval_id(api, client):
    route = api.post("/v1/toolkits/call").respond(json={"object": "tool_result", "name": "search", "content": "x"})
    nc.Toolkit(["search"]).call("search", {"query": "q"}, approval_id="ap_2")
    assert body(route.calls.last.request) == {"name": "search", "arguments": {"query": "q"}, "approval_id": "ap_2"}


def _tool_result(name, content, **extra):
    return httpx.Response(200, json={"object": "tool_result", "name": name, "content": content, **extra})


# What toolkits/service answers: a hold for someone else carries neither link, request nor operation;
# one addressed to the caller carries all three, the operation as its full object.
HELD = {"approval_id": "ap_9", "request_id": None, "approve_url": None, "operation": None, "approver": "owner"}
HELD_FOR_YOU = {"approval_id": "ap_8", "request_id": "hr_8", "approve_url": "https://noclick.com/h/hr_8",
                "operation": operation(op_id="op_8", kind="human.approve"), "approver": "user"}


def _policy_responder(request):
    # The shapes /v1/toolkits/call answers a refused or held call with: never an HTTP error.
    name = body(request)["name"]
    if name == "gmail__delete_email":
        return _tool_result(name, "gmail.delete_email is denied by policy. Ask the account owner to change the policy.",
                            is_error=True)
    if name == "gmail__send_email":
        return _tool_result(name, "This call is waiting for the account owner's approval.", is_error=True,
                            approval_required=HELD)
    if name == "gmail__forward_email":
        return _tool_result(name, "This call is waiting for your approval.", is_error=True,
                            approval_required=HELD_FOR_YOU)
    return _tool_result(name, "found it", is_error=False)


def test_handle_reports_policy_refusals_to_the_model(api, client):
    api.post("/v1/toolkits/call").mock(side_effect=_policy_responder)
    blocks = nc.Toolkit(["gmail", "search"]).handle([
        {"type": "tool_use", "id": "t1", "name": "gmail__delete_email", "input": {}},
        {"type": "tool_use", "id": "t2", "name": "gmail__send_email", "input": {}},
        {"type": "tool_use", "id": "t3", "name": "search", "input": {"query": "cake"}},
        {"type": "tool_use", "id": "t4", "name": "gmail__forward_email", "input": {}},
    ])
    by_id = {b["tool_use_id"]: b for b in blocks}
    assert by_id["t1"]["is_error"] and "denied by policy" in by_id["t1"]["content"]
    assert "change the policy" in by_id["t1"]["content"]
    assert by_id["t2"]["is_error"] and "waiting for the account owner's approval" in by_id["t2"]["content"]
    assert by_id["t4"]["is_error"] and "waiting for your approval" in by_id["t4"]["content"]
    seen_by_model = json.dumps(blocks)  # the model never sees an approval, its link or its operation
    assert not any(secret in seen_by_model for secret in ("ap_9", "ap_8", "hr_8", "op_8"))
    assert by_id["t3"] == {"type": "tool_result", "tool_use_id": "t3", "content": "found it", "is_error": False}
    denied = nc.Toolkit(["gmail"]).call("gmail__delete_email")  # call() returns it for your own code too
    assert denied.is_error and denied.approval_required is None
    held = nc.Toolkit(["gmail"]).call("gmail__send_email")
    assert held.approval_required == HELD and held.approve_url is None
    yours = nc.Toolkit(["gmail"]).call("gmail__forward_email")
    assert yours.approve_url == "https://noclick.com/h/hr_8"
    assert yours.approval_required["operation"]["id"] == "op_8"
    assert yours.approval_required["operation"]["object"] == "operation"
    assert held.approval is None and yours.approval.request_id == "hr_8"


def test_handle_helpers_pass_held_calls_to_on_approval(api, client):
    api.post("/v1/toolkits/call").mock(side_effect=_policy_responder)
    toolkit = nc.Toolkit(["gmail", "search"])
    seen = []
    toolkit.handle([
        {"type": "tool_use", "id": "t1", "name": "search", "input": {}},
        {"type": "tool_use", "id": "t2", "name": "gmail__send_email", "input": {"to": "a@b.c"}},
    ], on_approval=seen.append)
    assert [(r.name, r.approval_required) for r in seen] == [("gmail__send_email", HELD)]

    async def relay(result):
        seen.append(result)

    messages = toolkit.handle_openai([
        {"id": "c1", "type": "function", "function": {"name": "gmail__send_email", "arguments": "{}"}},
        {"id": "c2", "type": "function", "function": {"name": "search", "arguments": "{bad"}},
        {"id": "c3", "type": "function", "function": {"name": "gmail__delete_email", "arguments": "{}"}},
    ], on_approval=relay)
    assert len(seen) == 2 and seen[1].approval_required == HELD
    assert [m["tool_call_id"] for m in messages] == ["c1", "c2", "c3"]
    assert "ap_9" not in json.dumps(messages)


def test_other_errors_still_abort_handle(api, client):
    api.post("/v1/toolkits/call").respond(402, json={"error": {"type": "payment_required", "message": "no"}})
    with pytest.raises(nc.PaymentRequired):
        nc.Toolkit(["search"]).handle([{"type": "tool_use", "id": "t1", "name": "search", "input": {}}])


# --- usage -----------------------------------------------------------------------

USAGE = {"object": "usage", "period": "2026-09", "total_usd": 12.5, "group_by": "user", "groups": [
    {"id": USER_ID, "usd": 10.0, "events": 40}, {"id": "t2", "usd": 2.5, "events": 3},
]}


def test_usage_grouped_by_user(api, client):
    route = api.get("/v1/usage").respond(json=USAGE)
    spend = nc.usage(group_by="user")
    assert route.calls.last.request.url.params["period"] == "month"
    assert route.calls.last.request.url.params["group_by"] == "user"
    assert (spend.period, spend.total_usd) == ("2026-09", 12.5)
    assert [(g.id, g.usd, g.events) for g in spend.groups] == [(USER_ID, 10.0, 40), ("t2", 2.5, 3)]
    assert spend[USER_ID].usd == 10.0
    # An id that spent nothing is $0, not a KeyError; get() tells the two apart.
    assert (spend["nobody"].usd, spend["nobody"].events) == (0.0, 0)
    assert spend.get("nobody") is None and spend.get("nobody", "none") == "none" and spend.get(USER_ID).usd == 10.0
    assert "NoClick-User" not in route.calls.last.request.headers
    route.respond(json={**USAGE, "group_by": None, "groups": []})
    with pytest.raises(ValueError, match="group_by"):
        nc.usage()["nobody"]


def test_usage_grouped_by_person_names_each(api, client):
    route = api.get("/v1/usage").respond(json={**USAGE, "group_by": "person", "groups": [
        {"id": "login-ana", "name": "Ana", "usd": 9.0, "events": 30}, {"id": None, "name": None, "usd": 3.5, "events": 2},
    ]})
    spend = nc.usage(group_by="person")
    assert route.calls.last.request.url.params["group_by"] == "person"
    assert [(g.id, g.name, g.usd) for g in spend.groups] == [("login-ana", "Ana", 9.0), (None, None, 3.5)]
    assert spend["login-ana"].name == "Ana" and spend["nobody"].name is None


def test_usage_grouped_by_workstream_names_each(api, client):
    route = api.get("/v1/usage").respond(json={**USAGE, "group_by": "workstream", "groups": [
        {"id": "ws_1", "name": "Bakery site", "usd": 9.0, "events": 30}, {"id": None, "name": None, "usd": 3.5, "events": 2},
    ]})
    spend = nc.usage(group_by="workstream")
    assert route.calls.last.request.url.params["group_by"] == "workstream"
    assert [(g.id, g.name, g.usd) for g in spend.groups] == [("ws_1", "Bakery site", 9.0), (None, None, 3.5)]


def test_workstreams_are_listed_with_their_spend_and_renamed_by_name(api, client):
    listed = api.get("/v1/workstreams").respond(json={"object": "list", "unnamed_usd": 3.5, "data": [
        {"object": "workstream", "id": "ws_1", "name": "Bakery site", "spent_usd": 9.0, "events": 30,
         "created_at": "2026-11-20T10:00:00+00:00", "updated_at": "2026-11-20T10:00:00+00:00"},
    ]})
    [site] = nc.Workstream.list(user="user_42")
    assert listed.calls.last.request.headers["noclick-user"] == "user_42"
    assert (site.id, site.name, site.spent_usd, site.events) == ("ws_1", "Bakery site", 9.0, 30)
    assert site.created_at.year == 2026
    renamed = api.patch("/v1/workstreams/web%2Fsite%20old").respond(json={
        "object": "workstream", "id": "ws_1", "name": "Bakery site", "created_at": "2026-11-20T10:00:00+00:00",
        "updated_at": "2026-11-21T10:00:00+00:00", "merged_from": {"id": "ws_2", "name": "Menu"}})
    merged = nc.Workstream.rename("web/site old", "Bakery site")
    assert body(renamed.calls.last.request) == {"name": "Bakery site"}
    assert "noclick-user" not in renamed.calls.last.request.headers
    assert (merged.id, merged.name, merged.raw["merged_from"]["name"]) == ("ws_1", "Bakery site", "Menu")
    by_id = api.patch("/v1/workstreams/ws_1").respond(json={**renamed.calls.last.response.json(), "name": "Bakery"})
    assert nc.Workstream.rename(site, "Bakery").name == "Bakery" and by_id.called


def test_a_workstream_is_archived_brought_back_and_listed_apart(api, client):
    row = {"object": "workstream", "id": "ws_1", "name": "Q3 launch", "created_at": "2026-11-20T10:00:00+00:00",
           "updated_at": "2026-11-20T10:00:00+00:00"}
    change = api.patch("/v1/workstreams/Q3%20launch").mock(
        side_effect=lambda request: httpx.Response(200, json={**row, "archived": body(request)["archived"]}))
    archived = nc.Workstream.archive("Q3 launch")
    assert body(change.calls.last.request) == {"archived": True}
    assert "noclick-user" not in change.calls.last.request.headers
    assert archived.archived is True
    listed = api.get("/v1/workstreams").respond(json={"object": "list", "unnamed_usd": 0.0, "data": [
        {**row, "archived": True, "spent_usd": 2.0, "events": 4}]})
    [put] = nc.Workstream.list(archived=True)
    assert listed.calls.last.request.url.params["archived"] == "true"
    assert (put.id, put.archived, put.spent_usd) == ("ws_1", True, 2.0)
    nc.Workstream.list()
    assert "archived" not in listed.calls.last.request.url.params
    assert nc.Workstream.unarchive("Q3 launch").archived is False
    assert body(change.calls.last.request) == {"archived": False}


def test_an_operation_and_a_coding_job_name_their_workstream(api, client):
    named = {"id": "ws_1", "name": "Bakery site"}
    api.get("/v1/operations/op_1").respond(json={"object": "operation", "id": "op_1", "kind": "agent.task",
                                                 "status": "running", "workstream": named})
    assert nc.Operation.from_id("op_1").refresh().workstream == named
    from noclick.agent_extras import CodingJob

    job = CodingJob._from({"operation_id": "op_1", "status": "running", "text": "Hi.", "workstream": named})
    assert job.workstream == named
    assert CodingJob._from({"operation_id": "op_2", "status": "queued", "text": ""}).workstream is None


def test_usage_for_one_agent(api, client):
    route = api.get("/v1/usage").respond(json=USAGE)
    nc.usage(group_by="user", agent=nc.Agent.from_id("agt_1"))
    assert route.calls.last.request.url.params["agent_id"] == "agt_1"
    nc.usage()
    assert "agent_id" not in route.calls.last.request.url.params


async def test_usage_aio_follows_the_user(api, client):
    route = api.get("/v1/usage").respond(json={"period": "2026-09", "total_usd": 0, "groups": []})
    async with nc.as_user("user_42"):
        spend = await nc.usage.aio()
    assert spend.total_usd == 0.0 and spend.groups == []
    assert "group_by" not in route.calls.last.request.url.params
    assert route.calls.last.request.headers["NoClick-User"] == "user_42"


# --- policy ----------------------------------------------------------------------

POLICY = {"object": "policy", "user_id": None, "allow": [], "deny": ["*.delete_*"],
          "require_approval": ["gmail.send_email"]}


def test_policy_calls_follow_as_user_and_an_explicit_user_wins(api, client):
    route = api.get("/v1/policy").respond(json=POLICY)
    policy = nc.Policy.get()
    assert policy.deny == ["*.delete_*"] and policy.require_approval == ["gmail.send_email"]
    assert policy.allow == [] and policy.user_id is None
    assert "user_id" not in route.calls.last.request.url.params
    put = api.put("/v1/policy").mock(side_effect=lambda request: httpx.Response(200, json={
        "object": "policy", **body(request)}))
    evaluate = api.post("/v1/policy/evaluate").respond(json={"results": []})
    with nc.as_user("user_42"):
        nc.Policy.get()
        assert route.calls.last.request.url.params["user_id"] == "user_42"
        # A bare set inside as_user writes that user's policy, never the account's.
        nc.Policy.set(deny=["*.delete_*"])
        assert body(put.calls.last.request)["user_id"] == "user_42"
        nc.Policy.evaluate("search")
        assert body(evaluate.calls.last.request) == {"tools": ["search"], "user_id": "user_42"}
        # user=None still means the account's, and an explicit user wins.
        nc.Policy.set(deny=["slack.*"], user=None)
        assert "user_id" not in body(put.calls.last.request)
        nc.Policy.get(user="user_7")
        assert route.calls.last.request.url.params["user_id"] == "user_7"
    for call in (*route.calls, *put.calls, *evaluate.calls):
        assert "NoClick-User" not in call.request.headers


def test_policy_for_a_user_by_your_id(api, client):
    route = api.get("/v1/policy").respond(json={**POLICY, "user_id": "user_42", "allow": ["search"]})
    policy = nc.Policy.get(user="user_42")
    assert route.calls.last.request.url.params["user_id"] == "user_42"
    assert "NoClick-User" not in route.calls.last.request.headers
    assert policy.allow == ["search"] and policy.user_id == "user_42"


def test_policy_set_replaces_rules(api, client):
    route = api.put("/v1/policy").mock(side_effect=lambda request: httpx.Response(200, json={
        "object": "policy", **body(request)}))
    policy = nc.Policy.set(deny=["*.delete_*"], require_approval=("gmail.send_email",))
    assert body(route.calls.last.request) == {
        "allow": [], "deny": ["*.delete_*"], "require_approval": ["gmail.send_email"]}
    assert policy.deny == ["*.delete_*"]
    user = nc.User.from_id(USER_ID)
    policy = nc.Policy.set(allow=["gmail.*", "search"], user=user)
    assert body(route.calls.last.request)["user_id"] == USER_ID and policy.user_id == USER_ID
    assert "NoClick-User" not in route.calls.last.request.headers


def test_policy_set_refuses_a_bare_string():
    with pytest.raises(TypeError, match="list of patterns"):
        nc.Policy.set(deny="*.delete_*")


# --- brand -----------------------------------------------------------------------

BRAND = {"object": "brand", "name": "Acme", "logo_url": "https://acme.ai/logo.png", "color": "#ff5500",
         "support_url": "https://acme.ai/help", "email_from_name": "Acme Assistant"}


def test_brand_get_and_set(api, client):
    api.get("/v1/brand").respond(json=BRAND)
    put = api.put("/v1/brand").respond(json={**BRAND, "color": "#000000"})
    brand = nc.Brand.get()
    assert (brand.name, brand.color, brand.email_from_name) == ("Acme", "#ff5500", "Acme Assistant")
    with nc.as_user("user_42"):  # one brand per account: never user-scoped
        updated = nc.Brand.set(name="Acme", color="#000000")
    assert body(put.calls.last.request) == {"name": "Acme", "color": "#000000"}
    assert "NoClick-User" not in put.calls.last.request.headers
    assert updated.color == "#000000" and updated.support_url == "https://acme.ai/help"


def test_brand_update_sends_only_what_changes(api, client):
    patch = api.patch("/v1/brand").respond(json={**BRAND, "color": "#000000", "support_url": None})
    updated = nc.Brand.update(color="#000000", support_url=None)
    # Left out stays as it is; None clears.
    assert body(patch.calls.last.request) == {"color": "#000000", "support_url": None}
    assert "NoClick-User" not in patch.calls.last.request.headers
    assert (updated.name, updated.color, updated.support_url) == ("Acme", "#000000", None)


GOOGLE_APP = "6f1c2a4e-0b8d-4c55-9a43-2f0e9d7b1a11"


def test_brand_oauth_apps_name_your_app_per_provider(api, client):
    view = {**BRAND, "oauth_apps": {"google": GOOGLE_APP},
            "oauth_redirect_urls": {"google": "https://noclick.com/api/auth/google/callback"}}
    put = api.put("/v1/brand").respond(json=view)
    brand = nc.Brand.set(name="Acme", oauth_apps={"google": GOOGLE_APP})
    assert body(put.calls.last.request) == {"name": "Acme", "oauth_apps": {"google": GOOGLE_APP}}
    assert brand.oauth_apps == {"google": GOOGLE_APP}
    assert brand.oauth_redirect_urls["google"].endswith("/api/auth/google/callback")

    patch = api.patch("/v1/brand").respond(json={**BRAND, "oauth_apps": {}, "oauth_redirect_urls": {}})
    nc.Brand.update(oauth_apps={"google": None})  # back to NoClick's app; other providers kept
    assert body(patch.calls.last.request) == {"oauth_apps": {"google": None}}
    assert nc.Brand.update(oauth_apps=None).oauth_apps == {}
    assert body(patch.calls.last.request) == {"oauth_apps": None}


async def test_brand_aio(api, client):
    api.get("/v1/brand").respond(json=BRAND)
    assert (await nc.Brand.get.aio()).logo_url == "https://acme.ai/logo.png"


def test_retry_after_4xx_is_not_retried_for_spend_caps(api, client):
    route = api.post("/v1/sandboxes").respond(402, json={"error": {
        "type": "spend_cap_exceeded", "message": "cap", "cap": 1, "spent": 1, "scope": "key"}})
    with pytest.raises(nc.SpendCapExceeded):
        nc.Sandbox.create()
    assert route.call_count == 1 and client.sleeps == []
