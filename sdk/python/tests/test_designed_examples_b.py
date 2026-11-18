"""What the examples asked of connections, tools, policy, AI and data (designed, not built
yet): checkouts, bound arguments, bucket tools, the upsert tool, toolkit callbacks, AI
headers and speakers, policy rules, queue delivery options and folder commits, against
the mocked API."""

import asyncio
import hashlib

import httpx
import pytest

import noclick as nc
from platform_helpers import agent_row, body, listing, operation

GITHUB = {"object": "connection", "id": "cn_1", "name": "github", "integration": "github", "user_id": None,
          "status": "connected"}
DANA_GITHUB = {**GITHUB, "id": "cn_2", "user_id": "dana"}
BUCKET = {"object": "bucket", "id": "bkt_1", "name": "uploads", "public": False, "used_by": [], "user_id": None,
          "notifications": [], "created_at": "2026-09-25T10:00:00Z"}
QUEUE = {"object": "queue", "id": "que_1", "name": "new-recordings", "depth": 0, "in_flight": 0,
         "dead_letter_count": 0, "max_attempts": 5, "used_by": [], "user_id": None,
         "created_at": "2026-09-25T10:00:00Z"}


def _tool_result(name, content, **extra):
    return {"object": "tool_result", "name": name, "content": content, "is_error": False, "needs_connection": None,
            **extra}


# --- repos in an agent's workspace ----------------------------------------------------

def test_checkouts_say_where_and_what_may_be_pushed(api, client):
    api.get("/v1/connections/github").respond(json=GITHUB)
    github = nc.Connection.from_name("github")
    docs = github.checkout("acme/docs", push="noclick/*")
    assert (docs.repository, docs.branch, docs.path, docs.push) == ("acme/docs", None, None, ["noclick/*"])
    api_ref = github.checkout("acme/api", branch="release-2.4", path="refs/api/", push=["fix/*", "release-2.4"])
    assert (api_ref.path, api_ref.push) == ("refs/api", ["fix/*", "release-2.4"])
    site = nc.Repo.from_id("rp_1").checkout(path="site")

    assert asyncio.run(docs._wire(None)) == {"connection": "github", "repository": "acme/docs", "push": ["noclick/*"]}
    assert asyncio.run(site._wire(None)) == {"repo_id": "rp_1", "path": "site"}

    for bad in ("docs", "acme docs/x"):
        with pytest.raises(ValueError, match="owner/name"):
            github.checkout(bad)
    for bad in ("../etc", "/workspace/docs"):
        with pytest.raises(ValueError, match="under /workspace"):
            github.checkout("acme/docs", path=bad)
    with pytest.raises(ValueError, match="read-only"):
        github.checkout("acme/docs", push=[])
    # A git endpoint enforces exact branches and prefixes ending in '/*', nothing else.
    for bad in ("fix-*", "**", "noclick/*/wip", "*"):
        with pytest.raises(ValueError, match="isn't a push pattern"):
            github.checkout("acme/docs", push=["main", bad])


def test_an_agent_clones_its_checkouts_and_another_scopes_connection_goes_by_id(api, client):
    api.get("/v1/connections/github").respond(json=GITHUB)
    created = api.post("/v1/agents").respond(json=agent_row(id="ag_2", name="docs-writer", user_id="dana"))
    github = nc.Connection.from_name("github")   # the account's
    with nc.as_user("dana"):
        nc.Agent.create("docs-writer", instructions="Fix the docs.", repos=[github.checkout("acme/docs", push="noclick/*")])
    assert body(created.calls.last.request)["repos"] == [
        {"connection": "connection:cn_1", "repository": "acme/docs", "push": ["noclick/*"]},
    ]


# --- bound arguments --------------------------------------------------------------------

def test_bound_operations_go_out_as_objects_and_name_only_the_user(api, client):
    api.get("/v1/connections/gmail").respond(json={**GITHUB, "id": "cn_3", "name": "gmail", "integration": "gmail"})
    agent = api.post("/v1/agents").respond(json=agent_row())
    gmail = nc.Connection.from_name("gmail")
    send = gmail.only("send_email_message").bind(to="{{user.email}}")
    signed = send.bind(signature="{{ user.metadata.signature }}")
    assert send.bindings == {"to": "{{user.email}}"}   # bind returns a new ref
    assert signed.bindings == {"to": "{{user.email}}", "signature": "{{ user.metadata.signature }}"}

    nc.Agent.create("assistant", instructions="hi", tools=[gmail.only("fetch_emails_from_inbox"), signed, "search"])
    assert body(agent.calls.last.request)["tools"] == [
        "gmail.fetch_emails_from_inbox",
        {"tool": "gmail.send_email_message", "bind": {"to": "{{user.email}}", "signature": "{{ user.metadata.signature }}"}},
        "search",
    ]

    with pytest.raises(ValueError, match="isn't something NoClick fills in"):
        gmail.only("send_email_message").bind(to="{{user.phone}}")
    with pytest.raises(ValueError, match="isn't something NoClick fills in"):
        gmail.only("send_email_message").bind(cc=["ops@acme.com", "{{secrets.key}}"])
    with pytest.raises(ValueError, match="at least one"):
        gmail.only("send_email_message").bind()


def test_tools_read_back_from_an_agent_go_out_unchanged(api, client):
    bound = {"tool": "gmail.send_email_message", "bind": {"to": "{{user.email}}"}}
    person = {"human": {"email": "ops@acme.com"}, "tools": ["notify", "ask"]}
    api.get("/v1/agents/ag_1").respond(json=agent_row(tools=["search", bound, person]))
    patch = api.patch("/v1/agents/ag_1").respond(json=agent_row(tools=["search", bound, person]))
    agent = nc.Agent.get("ag_1")
    agent.update(tools=agent.tools)
    assert body(patch.calls.last.request)["tools"] == ["search", bound, person]
    with pytest.raises(TypeError):
        agent.update(tools=[{"tool": "gmail.send_email_message"}])   # neither a bound operation nor a person


def test_a_database_upsert_tool_is_bound_to_one_table(api, client):
    agent = api.post("/v1/agents").respond(json=agent_row())
    leads = nc.Database.from_id("db_1")
    upsert = leads.only("upsert").bind(table="enriched", owner="{{user.id}}")
    nc.Agent.create("researcher", instructions="hi", tools=[upsert, leads.only("query").bind(limit=50)])
    assert body(agent.calls.last.request)["tools"] == [
        {"tool": "database:db_1.upsert", "bind": {"table": "enriched", "owner": "{{user.id}}"}},
        {"tool": "database:db_1.query", "bind": {"limit": 50}},
    ]
    with pytest.raises(ValueError, match="bind it"):
        nc.Agent.create("researcher", instructions="hi", tools=[leads.only("upsert")])
    with pytest.raises(ValueError, match="or upsert, with its table bound"):
        leads.only("insert")


def test_a_bucket_is_five_tools_and_a_prefix_binds_a_folder(api, client):
    agent = api.post("/v1/agents").respond(json=agent_row())
    uploads = nc.Bucket.from_id("bkt_1")
    per_user = uploads.only("objects", "put", "signed_url").bind(prefix="users/{{user.id}}/")
    nc.Agent.create("assistant", instructions="hi", tools=[per_user, nc.Bucket.from_id("bkt_2")])
    assert body(agent.calls.last.request)["tools"] == [
        {"tool": f"bucket:bkt_1.{op}", "bind": {"prefix": "users/{{user.id}}/"}} for op in ("objects", "put", "signed_url")
    ] + ["bucket:bkt_2"]
    with pytest.raises(ValueError, match="objects, head, put, signed_url, remove, not read"):
        uploads.only("read")


def test_a_toolkit_sends_its_bound_refs_with_each_call(api, client):
    call = api.post("/v1/toolkits/call").respond(json=_tool_result("gmail__send_email_message", "sent"))
    api.get("/v1/connections/gmail").respond(json={**GITHUB, "id": "cn_3", "name": "gmail", "integration": "gmail"})
    gmail = nc.Connection.from_name("gmail")
    toolkit = nc.Toolkit([gmail.only("send_email_message").bind(to="{{user.email}}"), "search", nc.Bucket.from_id("bkt_1")])
    assert toolkit.tools == ["gmail.send_email_message", "search", "bkt_1"]
    toolkit.call("gmail__send_email_message", {"subject": "Hi"})
    assert body(call.calls.last.request)["tools"] == [
        {"tool": "gmail.send_email_message", "bind": {"to": "{{user.email}}"}}, "search", "bucket:bkt_1",
    ]
    toolkit.call("gmail__send_email_message", {"subject": "Hi"}, user="user_42")   # the account's gmail, shared
    assert body(call.calls.last.request)["tools"][0]["tool"] == "connection:cn_3.send_email_message"
    # Plain names still resolve server-side, without refs.
    nc.Toolkit(["gmail", "search"]).call("search", {"query": "x"})
    assert "tools" not in body(call.calls.last.request)


def test_an_mcp_server_serves_bound_operations(api, client):
    api.get("/v1/connections/hubspot").respond(json={**GITHUB, "id": "cn_4", "name": "hubspot", "integration": "hubspot"})
    created = api.post("/v1/mcp_servers").respond(json={"object": "mcp_server", "id": "mcp_1", "name": "crm-tools",
                                                        "tools": [], "url": "https://mcp.noclick.app/s/x"})
    hubspot = nc.Connection.from_name("hubspot")
    nc.McpServer.create("crm-tools", tools=[hubspot.only("search_contacts").bind(owner_id="7")])
    assert body(created.calls.last.request)["tools"] == [{"tool": "hubspot.search_contacts", "bind": {"owner_id": "7"}}]


# --- toolkit callbacks and results ------------------------------------------------------

HELD_FOR_YOU = {"approval_id": "ap_8", "request_id": "hr_8", "approve_url": "https://noclick.com/h/hr_8",
                "operation": operation(op_id="op_8", kind="human.approve"), "approver": "user"}
NEEDS = {"connection": "calendar", "integration": "google_calendar", "connect_url": "https://noclick.com/c/x"}


def _responder(request):
    name = body(request)["name"]
    if name == "calendar__create_event":
        return httpx.Response(200, json=_tool_result(name, "Connect Google Calendar first.", is_error=True,
                                                     needs_connection=NEEDS))
    if name == "gmail__send_email":
        return httpx.Response(200, json=_tool_result(name, "Waiting for your approval.", is_error=True,
                                                     approval_required=HELD_FOR_YOU))
    return httpx.Response(200, json=_tool_result(name, "found it"))


def test_on_connect_gets_each_result_that_needs_a_connection_with_its_call_id(api, client):
    api.post("/v1/toolkits/call").mock(side_effect=_responder)
    toolkit = nc.Toolkit(["gmail", "calendar", "search"])
    connects, approvals = [], []
    toolkit.handle([
        {"type": "tool_use", "id": "t1", "name": "search", "input": {"query": "x"}},
        {"type": "tool_use", "id": "t2", "name": "calendar__create_event", "input": {"title": "Lunch"}},
        {"type": "tool_use", "id": "t3", "name": "gmail__send_email", "input": {"to": "a@b.c"}},
    ], user="user_42", on_connect=connects.append, on_approval=approvals.append)
    [needs] = connects
    assert (needs.call_id, needs.arguments, needs.connect_url) == ("t2", {"title": "Lunch"}, "https://noclick.com/c/x")
    [held] = approvals
    assert (held.call_id, held.arguments) == ("t3", {"to": "a@b.c"})
    approval = held.approval
    assert isinstance(approval, nc.HumanRequest) and approval.id == "op_8" and approval.url == "https://noclick.com/h/hr_8"
    # Approved from your own code: the request it waits on is answered, not the policy approval.
    assert approval.request_id == "hr_8"
    answered = api.post("/v1/humans/requests/hr_8/answer").respond(json={
        "object": "human_request", "id": "hr_8", "kind": "approve", "status": "answered", "note": "Fine."})
    assert approval.approve(note="Fine.").request_status == "answered"
    assert body(answered.calls.last.request) == {"approved": True, "note": "Fine."}
    assert answered.calls.last.request.headers["NoClick-User"] == "user_42"

    async def seen(result):
        connects.append(result)

    toolkit.handle_openai([
        {"id": "c1", "type": "function", "function": {"name": "calendar__create_event", "arguments": "{}"}},
    ], on_connect=seen)
    assert connects[-1].call_id == "c1"
    assert toolkit.call("search").call_id is None and toolkit.call("search").approval is None


# --- AI --------------------------------------------------------------------------------

def test_ai_headers_carry_the_key_and_the_acting_user(client):
    assert nc.AI.headers() == {"Authorization": "Bearer nk_live_test"}
    with nc.as_user("user_42"):
        assert nc.AI.headers() == {"Authorization": "Bearer nk_live_test", "NoClick-User": "user_42"}
    assert nc.AI.headers(user=nc.User.from_id("user_7"))["NoClick-User"] == "user_7"


def test_transcribe_asks_for_speakers(api, client):
    route = api.post("/v1/ai/transcriptions").respond(json={
        "object": "transcript", "text": "Hi. Hello.", "language": "en", "duration_s": 4,
        "segments": [{"start_s": 0, "end_s": 1, "text": "Hi.", "speaker": "rep"},
                     {"start_s": 1, "end_s": 4, "text": "Hello.", "speaker": "customer"}],
    })
    call = nc.AI.transcribe("https://example.com/demo.mp3", speakers=["rep", "customer"])
    assert body(route.calls.last.request) == {"url": "https://example.com/demo.mp3", "speakers": ["rep", "customer"]}
    assert [(s.speaker, s.text) for s in call.segments] == [("rep", "Hi."), ("customer", "Hello.")]
    nc.AI.transcribe(b"ID3", speakers=True)
    assert route.calls.last.request.url.params["speakers"] == "true"
    nc.AI.transcribe("https://example.com/demo.mp3")
    assert "speakers" not in body(route.calls.last.request)
    with pytest.raises(TypeError, match="list of names"):
        nc.AI.transcribe("https://example.com/demo.mp3", speakers="rep")


def test_a_long_transcription_runs_in_the_background_as_an_operation(api, client):
    start = api.post("/v1/ai/transcriptions").respond(202, json=operation(
        op_id="op_t", kind="ai.transcription", status="running", step="transcribing"))
    api.get("/v1/operations/op_t/wait").respond(json=operation(
        op_id="op_t", kind="ai.transcription", status="succeeded", result={
            "object": "transcript", "text": "Hi.", "language": "en", "duration_s": 5400.0, "cost_usd": 0.4,
            "segments": [{"start_s": 0, "end_s": 1, "text": "Hi.", "speaker": "speaker_1"}]}))
    job = nc.AI.transcribe("https://example.com/all-hands.mp3", speakers=True, background=True)
    assert isinstance(job, nc.Operation) and job.kind == "ai.transcription"
    assert body(start.calls.last.request) == {"url": "https://example.com/all-hands.mp3", "speakers": True,
                                              "background": True}
    meeting = job.wait()
    assert isinstance(meeting, nc.Transcript) and meeting.segments[0].speaker == "speaker_1"
    nc.AI.transcribe(b"ID3", speakers=["rep", "customer"], background=True)
    assert dict(start.calls.last.request.url.params) == {"speakers": "rep,customer", "background": "true"}


def test_a_models_price_with_speakers_is_its_own(api, client):
    api.get("/v1/ai/models").respond(json=listing(
        {"id": "noclick/transcribe-1", "kind": "transcription", "usd_per_minute": 0.004,
         "usd_per_minute_with_speakers": 0.005},
        {"id": "openrouter/google/gemini-3.5-flash", "kind": "transcription", "usd_per_minute": 0.006,
         "usd_per_minute_with_speakers": None}))
    ours, flash = nc.AI.models(kind="transcription")
    assert (ours.usd_per_minute, ours.usd_per_minute_with_speakers) == (0.004, 0.005)
    assert flash.usd_per_minute_with_speakers is None


# --- policy ----------------------------------------------------------------------------

POLICY = {"object": "policy", "user_id": None, "allow": [], "deny": ["*.delete_*"], "require_approval": [
    "gmail.*", {"tool": "stripe.create_refund", "when": "args.amount > 10000", "approver": {"email": "finance@acme.com"}},
    {"tool": "calendar.*", "approver": {"user": True}},
]}


def test_rules_carry_conditions_and_approvers_both_ways(api, client):
    put = api.put("/v1/policy").respond(json=POLICY)
    policy = nc.Policy.set(
        deny=["*.delete_*"],
        require_approval=[
            "gmail.*",
            nc.Rule("stripe.create_refund", when="args.amount > 10000", approver="finance@acme.com"),
            {"tool": "calendar.*", "approver": nc.Human()},
            nc.Rule("slack.*", approver=nc.Human(user="user_42")),
            nc.Rule("hubspot.*"),
        ],
    )
    assert body(put.calls.last.request)["require_approval"] == [
        "gmail.*",
        {"tool": "stripe.create_refund", "when": "args.amount > 10000", "approver": {"email": "finance@acme.com"}},
        {"tool": "calendar.*", "approver": {"user": True}},
        {"tool": "slack.*", "approver": {"user_id": "user_42"}},
        "hubspot.*",   # a rule with nothing more to say is its pattern
    ]
    refund = policy.require_approval[1]
    assert refund == nc.Rule("stripe.create_refund", "args.amount > 10000", "finance@acme.com")
    assert isinstance(policy.require_approval[2].approver, nc.Human)

    with pytest.raises(ValueError, match="Only a require_approval rule"):
        nc.Policy.set(deny=[nc.Rule("gmail.*", approver="a@b.c")])
    with pytest.raises(ValueError, match="by email"):
        nc.Policy.set(require_approval=[nc.Rule("gmail.*", approver=nc.Human(phone="+14155550100"))])
    with pytest.raises(TypeError, match="may have 'when', 'approver' and 'message'"):
        nc.Policy.set(require_approval=[{"tool": "gmail.*", "who": "x"}])


def test_add_and_remove_change_one_rule_on_the_server(api, client):
    add = api.post("/v1/policy/add").respond(json=POLICY)
    remove = api.post("/v1/policy/remove").respond(json=POLICY)
    nc.Policy.add(nc.Rule("quickbooks.create_bill", when="args.total_amount > 2500", approver="finance@acme.com"))
    assert body(add.calls.last.request) == {"list": "require_approval", "rules": [
        {"tool": "quickbooks.create_bill", "when": "args.total_amount > 2500", "approver": {"email": "finance@acme.com"}}]}
    with nc.as_user("user_42"):
        nc.Policy.add("slack.*", to="deny")
        assert body(add.calls.last.request) == {"list": "deny", "rules": ["slack.*"], "user_id": "user_42"}
        nc.Policy.remove("slack.*")
        assert body(remove.calls.last.request) == {"tools": ["slack.*"], "user_id": "user_42"}
    assert "NoClick-User" not in add.calls.last.request.headers
    with pytest.raises(ValueError, match="to is one of"):
        nc.Policy.add("slack.*", to="approve")
    with pytest.raises(ValueError, match="at least one"):
        nc.Policy.add(to="deny")


def test_evaluate_judges_one_call_by_its_arguments(api, client):
    route = api.post("/v1/policy/evaluate").respond(json={"results": [{
        "tool": "stripe.create_refund", "verdict": "approval", "matched_pattern": "stripe.create_refund",
        "layer": "account", "rule": POLICY["require_approval"][1]}]})
    [verdict] = nc.Policy.evaluate("stripe.create_refund", arguments={"amount": 25000}, user="user_42")
    assert body(route.calls.last.request) == {
        "tools": ["stripe.create_refund"], "arguments": {"amount": 25000}, "user_id": "user_42"}
    assert verdict.rule == nc.Rule("stripe.create_refund", "args.amount > 10000", "finance@acme.com")
    with pytest.raises(ValueError, match="one tool"):
        nc.Policy.evaluate(["a.b", "c.d"], arguments={})


# --- queues and buckets ------------------------------------------------------------------

def _message(mid):
    return {"object": "queue_message", "id": mid, "queue_id": "que_1", "body": {"key": "calls/1.mp3"},
            "status": "in_flight", "attempts": 1, "lease_id": f"lease_{mid}"}


def test_queue_dedupe_nack_error_and_drain(api, client):
    put = api.post("/v1/queues/que_1/messages").respond(json=listing({"id": "msg_1"}))
    nack = api.post("/v1/queues/que_1/messages/msg_1/nack").respond(204)
    take = api.get("/v1/queues/que_1/messages").mock(side_effect=[
        httpx.Response(200, json=listing(_message("msg_1"))),
        httpx.Response(200, json=listing()),
    ])
    jobs = nc.Queue.from_id("que_1")
    assert jobs.put({"order": "o_981"}, dedupe_key="order-o_981") == "msg_1"
    assert body(put.calls.last.request) == {"messages": [{"body": {"order": "o_981"}, "dedupe_key": "order-o_981"}]}

    drained = [msg for msg in jobs.iterate(stop_when_empty=True)]
    assert [m.id for m in drained] == ["msg_1"]
    assert all("wait_s" not in c.request.url.params for c in take.calls)   # short polls: it stops, never waits
    assert client.sleeps == []
    drained[0].nack(delay_s=30, error="The invoicing service answered 503")
    assert body(nack.calls.last.request) == {
        "lease_id": "lease_msg_1", "delay_s": 30, "error": "The invoicing service answered 503"}


def test_release_hands_a_message_back_without_spending_an_attempt(api, client):
    api.get("/v1/queues/que_1/messages").respond(json=listing(_message("msg_1")))
    release = api.post("/v1/queues/que_1/messages/msg_1/release").respond(204)
    msg = nc.Queue.from_id("que_1").get()
    msg.release(delay_s=3600)
    assert body(release.calls.last.request) == {"lease_id": "lease_msg_1", "delay_s": 3600}
    msg.release()
    assert body(release.calls.last.request) == {"lease_id": "lease_msg_1"}
    with pytest.raises(nc.InvalidRequest, match="nothing to ack, nack or release"):
        nc.QueueMessage._new(raw={"id": "msg_2", "queue_id": "que_1"}).release()


def test_a_bucket_tells_a_queue_about_new_files(api, client):
    api.get("/v1/queues/que_1").respond(json=QUEUE)
    added = api.post("/v1/buckets/bkt_1/notifications").respond(
        json={**BUCKET, "notifications": [{"queue": "new-recordings", "prefix": "calls/"}]})
    removed = api.post("/v1/buckets/bkt_1/notifications/remove").respond(json=BUCKET)
    bucket = nc.Bucket.from_id("bkt_1")
    bucket.notify(nc.Queue.from_id("que_1"), prefix="calls/")
    assert body(added.calls.last.request) == {"queue": "new-recordings", "prefix": "calls/"}
    assert bucket.notifications == [{"queue": "new-recordings", "prefix": "calls/"}]
    bucket.notify("new-recordings", prefix="calls/", enabled=False)
    assert body(removed.calls.last.request) == {"queue": "new-recordings", "prefix": "calls/"}
    assert bucket.notifications == []


# --- folder commits ----------------------------------------------------------------------

def _sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def test_committing_a_folder_sends_only_what_changed(api, client, tmp_path):
    (tmp_path / "dist" / "assets").mkdir(parents=True)
    (tmp_path / "dist" / "index.html").write_text("<h1>Hi</h1>")
    (tmp_path / "dist" / "assets" / "app.js").write_text("run()")
    (tmp_path / "dist" / "assets" / "app.js.map").write_text("{}")
    (tmp_path / "dist" / ".git").mkdir()
    (tmp_path / "dist" / ".git" / "HEAD").write_text("ref")
    api.get("/v1/repos/rp_1/branches").respond(json=listing({"name": "main", "head": "abc"}))
    files = api.get("/v1/repos/rp_1/files").respond(json=listing(
        {"path": "index.html", "type": "file", "size": 11, "sha": _sha(b"<h1>Hi</h1>")},
        {"path": "old.html", "type": "file", "size": 3, "sha": "x"},
        {"path": "keep.map", "type": "file", "size": 2, "sha": "y"},
    ))
    commits = api.post("/v1/repos/rp_1/commits").respond(json={"sha": "def", "message": "Rebuild", "files_changed": 2})
    site = nc.Repo.from_id("rp_1")

    commit = site.commit(tmp_path / "dist", message="Rebuild", exclude=["*.map"])
    assert commit.sha == "def"
    assert files.calls.last.request.url.params["recursive"] == "true"
    sent = {f["path"]: f for f in body(commits.calls.last.request)["files"]}
    assert sent == {"assets/app.js": {"path": "assets/app.js", "content": "cnVuKCk=", "encoding": "base64"},
                    "old.html": {"path": "old.html", "delete": True}}

    # A branch that doesn't exist yet is compared with the default branch.
    site.commit(str(tmp_path / "dist"), message="Try", branch="preview", exclude=["*.map"])
    assert "ref" not in files.calls.last.request.url.params

    files.respond(json=listing(
        {"path": "index.html", "type": "file", "sha": _sha(b"<h1>Hi</h1>")},
        {"path": "assets/app.js", "type": "file", "sha": _sha(b"run()")},
    ))
    calls = commits.call_count
    assert site.commit(tmp_path / "dist", message="Again", exclude=["*.map"]) is None
    assert commits.call_count == calls
