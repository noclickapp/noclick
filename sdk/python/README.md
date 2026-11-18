# noclick

Python client for the NoClick Platform API: act for your users (the people and
companies your product acts for, each known by your own id for them), connect
their accounts, give your LLM tools, reach a human, run hosted agents,
and give them inboxes, phone numbers and sandboxes.
It works with NoClick's hosted platform; a self-hosted instance doesn't serve this API yet.
From 0.2 the `noclick` package is this client; the workflow client it replaces stays at 0.1.x.

```bash
pip install noclick
export NOCLICK_API_KEY=nk_live_...          # a platform key with the scopes you need
# NOCLICK_API_URL defaults to https://api.noclick.com
```

## Quick tour

```python
import noclick

user = noclick.User.from_id("user_42", create_if_missing=True, email="ana@example.com")

with noclick.as_user(user):
    # A named connection: pending until Ana connects her Gmail at connect_url
    gmail = noclick.Connection.from_name("gmail", integration="gmail", create_if_missing=True,
                                         redirect_url="https://acme.ai/done")
    print(gmail.connect_url)                 # send your user here
    gmail.wait()                             # blocks until they've connected

    toolkit = noclick.Toolkit(["search", "gmail.send_email_message"])   # the connection named gmail
    ok = user.human.approve("Send the weekly summary to your team?").wait()   # True / False

    # Ana's own agent: uses her connections; may ask her for a calendar when it needs one
    assistant = noclick.Agent.from_name("assistant", create_if_missing=True, instructions="You run Ana's day.",
                                        tools=[gmail, "search"], can_request=["google_calendar"])
    print(assistant.message("What's on today?").text)
```

## Ideas

- **Lazy objects.** `User.from_id(...)`, `Connection.from_name(...)`,
  `Agent.from_name(...)`, `Operation.from_id(...)` send nothing until used;
  `create_if_missing=True` creates on first use (a concurrent create is
  adopted, not duplicated). Given fields, `Agent.from_name` (and the others
  that take them) sets them on the one it finds, on every run, with or without
  `create_if_missing`: one you leave out is never changed, one it can't set on
  an existing agent, like `ttl_s`, raises `Conflict`, and the grants its user
  gave the agent are kept.
  `create(..., allow_existing=True)` makes one once and returns it untouched after.
- **Named connections.** Code, toolkits and agents name a connection
  (`"gmail"`, or a `Connection`), so they always act in exactly that account;
  two accounts on one service are two names. An agent's connections are its
  own scope's: a user's agent uses the user's, an account agent the
  account's. A name that is no connection there names an integration's
  operations that need no account, on NoClick's key: `tools=["exa.search"]`
  and `noclick.run("exa.search", {...})` work for every user with nothing
  connected, and a connection named `exa` holding your own key takes over
  the same refs.
- **Blocking or async, same method.** Every method blocks; `.aio` is the
  coroutine: `await agent.message.aio("hi")`. Blocking calls run on a private
  loop thread, so they also work in Jupyter and inside running event loops.
- **Users, by your id.** A user's id is your own id for them: 1 to 255
  printable ASCII characters, without spaces or `/`, other than `all` and
  `none`. `with noclick.as_user(user_or_id):` (or `async with`) scopes every
  call inside it, sending the id as is in the `NoClick-User` header; any
  method's `user=` wins. Objects a user owns (its connections and agents)
  always act for that user; shared objects (`Toolkit`, `Human()`,
  account-level agents) follow the user current at each call, so
  one module-level toolkit serves every user (its connection names resolve
  among each call's user's).
- **Operations.** Anything that waits on the world returns an `Operation`;
  `.wait(timeout=)` long-polls and returns the typed outcome (`Connection`,
  `Answer`, `bool`, `AgentReply`) or raises the typed error. `.events()` yields
  status changes, `.cancel()` cancels.
- **Errors** carry `.type`, `.message`, `.next_step` and `.details` (read as
  attributes): `noclick.NeedsConnection` and `noclick.CredentialDisconnected` have
  `.connection` and `.connect_url`, `noclick.Conflict` has
  `.existing_id`, `noclick.PaymentRequired` has `.balance_usd` and `.required_usd`
  (dollars), plus `noclick.ApprovalRequired`,
  `noclick.PermissionDenied`, `noclick.NotFound`, `noclick.RateLimited`, ...
- **Safe retries.** 408/429/5xx and connection errors retry with backoff
  (honouring `Retry-After`); each write carries one `Idempotency-Key` for all
  its attempts. A POST's 500 is not retried, nor an answer the server replays
  for that key (`Idempotent-Replayed`); an error says how many times the call
  was sent (`err.attempts`).

## Tools for your LLM

```python
import anthropic

toolkit = noclick.Toolkit(["gmail", "search"])
messages = [{"role": "user", "content": "Email Ana the lemon cake recipe"}]
with noclick.as_user("user_42"):
    while True:
        response = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=1024, tools=toolkit.definitions(), messages=messages)
        if response.stop_reason != "tool_use":
            break
        messages += [{"role": "assistant", "content": response.content},
                     {"role": "user", "content": toolkit.handle(response)}]
```

OpenAI: `toolkit.definitions("openai")` and `messages += toolkit.handle_openai(completion)`
(Responses API `function_call` items work too). Connection tools are named
`{connection}__{operation}`. A tool whose connection has no account yet returns a
normal result telling the model so, with the link; `toolkit.call(...)` exposes it
as `result.needs_connection` / `result.connect_url`.

A tool call never raises for policy: a denied call, or one held for approval,
comes back as an error result the model reads. A hold's details are kept out
of the model's view, in `result.approval_required` (`approval_id`,
`request_id`, `approve_url`, `operation`, `approver`: `"user"` or `"owner"`).
`request_id` (the request a person answers), `approve_url` and `operation` (the
approval's operation object) are `None` unless the request is addressed to
you; the approver is emailed either way. The `handle` helpers hand each held
call to `on_approval`:

```python
blocks = toolkit.handle(response, on_approval=lambda r: notify(r.approval_required))
```

Once the person approves, the model's retry of the identical call goes through.

No model key of your own? `noclick.AI` runs chat, embeddings, images and transcription paid
from your NoClick balance, and `noclick.AI.base_url` is an OpenAI-compatible endpoint (chat
completions, responses, embeddings, models) for any OpenAI client, where your agents are models too:

```python
reply = noclick.AI.chat(messages, tools=toolkit.definitions("openai"))   # OpenRouter ids: openrouter/...
answer = noclick.AI.chat("Where's my refund?", model="agent:support")   # conversation=answer.conversation continues it
```

## More

```python
slack = noclick.Connection.from_name("slack", user="user_42")
slack.lookup("channel", search="gen")                                # options for an ID field
gmail.run("send_email_message", {"to": ["a@b.c"], "subject": "Hi", "body": "..."})
slack.operations(search="message"); slack.operation("send_message_to_channel").parameters   # what it can do
noclick.Connection.integrations("mail")                              # find a service: name, label, connect_with
noclick.run("exa.search", {"query": "..."})                          # needs no account: no connection, NoClick's key
noclick.run("gmail.send_email_message", {...}, user="user_42")       # the same ref runs through a connection named gmail
gmail.request(reason="to send your summaries").wait()                # emails a fresh link to the user
gmail.token().access_token                                           # OAuth only, credentials:token scope
noclick.Connection.create("crm", credential_type="affinity_api_key", data={"api_key": "..."})   # a key you hold
for grant in assistant.grants():                                     # connections its user gave it
    print(grant.connection, grant.status)                            # assistant.revoke_grant(grant)
noclick.Human(email="ops@acme.ai").ask("Ship it?", options=["Yes", "No"]).wait().choice
reply = agent.message("Any lemon cake?")
agent.message("Two slices please", conversation=reply.conversation)   # same thread
agent.wake(reply.conversation, after=3600, note="Check the order shipped.")   # a turn later; agent.wakeups(), its wake_me tool
agent.memory.save("menu", "Lemon cake on Fridays.", description="What we bake when")   # it sees the line every turn
coder = noclick.Agent.create("coder", instructions="...", harness="claude_code", model_connection="claude")   # Agent.harnesses() lists them

run = noclick.Workflow.from_name("order-intake").run({"order_id": "o1"}).wait()   # one built in the app
print(run.outputs)
client = noclick.Client(api_key="nk_live_other", base_url="https://api.noclick.com")
noclick.User.list(client=client)                                        # or noclick.configure(api_key=...)
```

## Spend, policy, channels and sandboxes

```python
# Spend and caps
noclick.usage(group_by="user")["user_42"].usd             # this month, per user / key / agent
# any call can raise noclick.SpendCapExceeded (402) with .cap, .spent, .scope
est = noclick.estimate([{"kind": "project", "runtime": "edge", "usage": {"requests": 100_000}}, {"kind": "bucket"}])
print(est.monthly_usd, est.lines)                         # priced before anything is made; nothing is charged

# Policy: deny wins, a user policy narrows the account's
noclick.Policy.set(deny=["*.delete_*"], require_approval=["gmail.send_email_message"])
noclick.Policy.set(allow=["search", "gmail.*"], user="user_42")
try:
    gmail.run("send_email_message", args)
except noclick.ApprovalRequired as pending:                    # a Human.approve went out
    if pending.operation.wait():                               # True once approved
        gmail.run("send_email_message", args, approval_id=pending.approval_id)
# a Toolkit never raises: a denied or held tool is an error result (see "Tools for your LLM")

noclick.Brand.set(name="Acme", logo_url="https://acme.ai/logo.png", color="#ff5500")   # /h/ pages + emails
user.verify_phone(); user.check_phone("123456")      # True; a wrong code raises noclick.InvalidRequest

# Agents with tools, children and A2A
planner = noclick.Agent.create("planner", instructions="...", tools=["gmail", "slack.send_message_to_channel"],
                               budget_usd_per_month=20)            # the account's gmail and slack connections
child = noclick.Agent.create("inbox-helper", instructions="Summarize the inbox.", parent_id=planner,
                             tools=["gmail.fetch_emails_from_inbox"], ttl_s=900, budget_usd_per_month=0.5)
planner.children()                                        # child too; expired past its ttl_s, readable 30 days
researcher = planner.spawn("Find three launches.", tools=["gmail"], conversation="launch",
                           updates=["blocked", noclick.Before("gmail.*"), noclick.Every(900)])   # starts at once
researcher.job.wait(); researcher.job.updates(); planner.jobs(status="live")   # each update wakes planner in "launch"
researcher.ask("Where are you?"); researcher.ask("Skip B.", interject=True)   # a snapshot, or into its running turn
planner.a2a_card(); planner.a2a_url                       # JSON-RPC endpoint, platform key as bearer

# Channels: agents, the user and remote A2A agents in one room (closed on exit)
with noclick.Channel.create("launch", members=[planner, user, "https://remote.ai/a2a"],
                            mode="mentions", max_agent_turns=20, budget_usd=2) as room:
    room.post("@planner draft the announcement", as_=user)
    for message in room.stream():                        # long-polls until the channel closes
        print(message.author.name, message.text)          # async: `async for m in room.stream.aio()`
        if message.author.name == "planner":
            break

# Sandboxes (terminated on exit, billed per second)
with noclick.Sandbox.create(image="python", timeout_s=600) as sb:
    sb.files.write("/tmp/data.csv", csv_bytes)
    result = sb.exec("python -c 'print(open(\"/tmp/data.csv\").read()[:80])'")
    print(result.exit_code, result.stdout, result.stderr)  # a non-zero exit is a result, not an error
```

## Sessions, inboxes and phone numbers

```python
# User sessions: a short-lived token pinned to one user, safe for a browser
session = user.session(scopes=["agents", "humans", "inbox"], ttl_s=3600)   # max 24h
session.token, session.expires_at                             # repr never shows the token
user_client = noclick.Client.for_session(session)           # same as noclick.Client(api_key=session.token)
noclick.Agent.list(client=user_client)                      # acts as that user, with those scopes only

# Agents can search and fetch; every agent can also run shell commands (a policy can deny `code`)
researcher = noclick.Agent.create("researcher", instructions="...", tools=["search", "fetch", gmail])

# Channels: list them; remote A2A agents can carry auth headers (stored encrypted, never shown back)
noclick.Channel.list(status="open", limit=20)
room.add(noclick.A2AMember("https://remote.ai/a2a", headers={"Authorization": "Bearer ..."}))
room.members[0].a2a_header_names                         # ["Authorization"]: names only

# Triggers and subscriptions: a URL or an app's events wake an agent, or post in a room as the app
orders = researcher.add_trigger(noclick.OnWebhook(name="orders", message="A new order arrived."))
print(orders.url)                                        # each POST is a turn
researcher.add_trigger(noclick.OnEvent("slack", "app_mention"))   # slack.events() lists the events
room.subscribe(noclick.OnEvent("stripe", "invoice_payment_failed"), wake=[planner])

# Workspaces: a company's channels, agents and people under one name, with a monthly cap
acme = noclick.Workspace.from_name("Acme", create_if_missing=True, members=[planner, noclick.User.from_id("ana")],
                                   budget_usd_per_month=200)
billing = noclick.Channel.create("billing", workspace=acme, members=[planner, noclick.User.from_id("ana")])
billing.post("@planner refund order 42", as_=noclick.User.from_id("ana"))   # each person as themselves
acme.subscribe(noclick.OnWebhook(name="deploys"), channels="all", wake="all")  # one source, every room

# Inboxes: an address your code or agent receives mail at
inbox = noclick.Inbox.create(local_part="signup", agent=researcher)   # agent= wakes it per message
print(inbox.address)
mail = inbox.wait_for(sender="noreply@github.com", subject_contains="code", timeout_s=300).wait()
print(mail.text, mail.attachments)                       # documents come with their text
mail.reply("Thanks!")                                    # to the sender only; no free-form outbound
for message in inbox.stream():                           # long-polls until you break
    ...

# Phone numbers (US local, monthly; noclick.NotAvailable outside the phone feature)
[pick] = noclick.PhoneNumber.available(area_code="415", limit=1)
number = noclick.PhoneNumber.buy(pick, max_monthly_usd=5)     # noclick.PriceExceeded above the ceiling
number.answer_with(host)                                      # inbound calls reach this agent
call = number.call("+14155550100", goal="Confirm Friday's 3pm booking.").wait()
print(call.text, call.seconds, call.cost_usd)           # call.transcript: [{role, text, at}, ...]
number.calls(); number.release()

# Regions: where a sandbox or an agent runs, for good (else your account's default)
print([r.name for r in noclick.regions()])                # ['us-east', 'us-west', 'eu', 'ap', 'in']
with noclick.Sandbox.create(region="eu") as sb:
    print(sb.region)

# Hosted MCP servers: a user's tools at one URL, for Claude, ChatGPT or Cursor
server = noclick.McpServer.from_name("crm-tools", tools=["hubspot", "search"], create_if_missing=True, user="acme")
print(server.url, server.tool_count, [c.name for c in server.clients()])

# Repos: a copy of a public git repository, history and all (wait() gives the Repo once it's copied)
blog = noclick.Repo.create("blog", from_url="https://github.com/acme/blog").wait()

# A repository in a coding agent's workspace; NoClick refuses a push outside agent/*
github = noclick.Connection.from_name("github", integration="github", create_if_missing=True)
fixer = noclick.Agent.from_name("fixer", create_if_missing=True, instructions="Fix the failing tests.",
                                harness="claude_code", model_connection="claude",
                                repos=[github.checkout("acme/web", push="agent/*")])

# Sandboxes: long commands in the background, within the sandbox's own lifetime
with noclick.Sandbox.create(timeout_s=3600) as sb:
    build = sb.exec("make all", background=True, timeout_s=1800)   # an Operation, up to 3600s
    print(build.wait().exit_code)                        # ExecResult, same as the blocking form

# Volumes: a folder that outlives the sandbox or turn that wrote it; buckets: files by key with signed links
data = noclick.Volume.from_name("datasets", create_if_missing=True)
data.write("/raw/orders.csv", b"id,total\no_1,42\n")
with noclick.Sandbox.create(volumes={"/data": data}) as sb:
    print(sb.exec("wc -l /data/raw/orders.csv").stdout)
uploads = noclick.Bucket.from_name("uploads", create_if_missing=True)
uploads.put("invoices/0042.pdf", b"%PDF-1.7 ...")
print(uploads.signed_url("invoices/0042.pdf", expires_in=3600))
files = noclick.Agent.from_name("filer", create_if_missing=True, instructions="File what users send you.",
                                tools=[uploads.only("put", "signed_url").bind(prefix="users/{{user.id}}/")])
print(files.workspace(user="acme").files())   # what it wrote for that user

# Secrets: write-only values in a sandbox's or an agent's shell environment
shipping = noclick.Secret.from_name("shipping", values={"SHIPPING_API_KEY": "sk-..."}, create_if_missing=True)
with noclick.Sandbox.create(secrets=[shipping], network=True) as sb:
    sb.exec("python track.py")                           # reads os.environ["SHIPPING_API_KEY"]

# Dicts: shared key-value state; queues: work delivered at least once, to code or to an agent
seen = noclick.Dict.from_name("processed-orders", create_if_missing=True)
if seen.put_if_absent("evt_9f2c", True, ttl_s=7 * 86400):
    print("first delivery", seen.increment("handled-today"))
jobs = noclick.Queue.from_name("invoices", create_if_missing=True)
jobs.put({"invoice": "INV-1042"}, dedupe_key="INV-1042")
for msg in jobs.iterate(stop_when_empty=True):
    print(msg.body)
    msg.ack()
chaser = noclick.Agent.from_name("chaser", create_if_missing=True, instructions="Chase unpaid invoices.",
                                 triggers=[noclick.OnQueue(jobs)])   # or each message is a turn, one at a time
```

## Activity: operations, tool calls, requests, usage

```python
# Pages: list() drains; list_page() returns one page and its cursor (every resource with a list)
page = noclick.Operation.list_page(kind="agent.message", status="live", limit=50)
more = noclick.Operation.list_page(kind="agent.message", status="live", cursor=page.next_cursor)

# Read across users without acting as one: user_filter is the user_id query, never the header
noclick.Agent.list(user_filter=noclick.ALL_USERS)         # noclick.NO_USER = account-level only
noclick.Agent.list(status="working", order="last_active")  # each: status, last_active_at, running_turns, child_count
noclick.Sandbox.list_page(user_filter="user_42")          # a User or your id for one

noclick.Operation.list(status="failed", created_after=datetime.now(timezone.utc) - timedelta(days=1))
noclick.Operation.summary(kind="agent.message", agent=planner).by_status   # {"running": 1, ...}
op = noclick.Operation.from_id("…")
op.wait_ms, op.run_ms, op.held_ms, op.transitions, op.tool_calls()
repr(op)   # on the hosted API: ..., console_url='https://noclick.com/dashboard/developers/operations?op=…'
# errors raised by op.wait() end with the same console link

noclick.ToolCall.list_page(tool="gmail.*", status="error", source="agent")
noclick.ToolCall.summary(since=since)                         # total, success, error
noclick.ApiRequest.list_page(method="POST", status="4xx", key="nk_live_ab12")   # writes and failures
noclick.HumanRequest.list_page(status="pending", kind="approve")
planner.conversations_page(user_filter=noclick.ALL_USERS)   # a user's own agent: owner sessions only (a key 404s; drop the filter)
noclick.Usage.series(group_by="agent")                        # daily lines this month; .limits() for caps
noclick.Policy.evaluate(["gmail.send_email_message"], draft={"layer": "account", "deny": ["gmail.*"]})
noclick.Policy.list(); noclick.Brand.reset()

# api_key may be a function (sync or async), asked on every attempt: a refreshing token
noclick.Client(api_key=lambda: session_store.current_token())

# Events, delivered to your server signed (Webhook.verify in your receiver), kept 30 days
hook = noclick.Webhook.from_name("https://api.yourco.test/noclick/events", create_if_missing=True,
                                 events=["operation.failed", "connection.*"])
noclick.Event.list(type="operation.failed", user_filter=noclick.ALL_USERS, limit=20)
planner.wake("launch", when="connection.connected", filters={"name": "gmail"}, note="Gmail is in: carry on.")
planner.add_trigger(noclick.OnPlatformEvent("operation.failed", filters={"kind": "agent.task"}))
room.subscribe("connection.disconnected")

# Charging your users: usage.recorded per step of their spend; pause them, in your words, when your billing says
user = noclick.User.from_id("user_42")
user.pause_spending(message="You've used your credits.", action=("Top up", "https://acme.test/top-up?u={{user.id}}"))
user.resume_spending()                                        # what they sent meanwhile runs now
noclick.User.list(spending="paused")
```

## The `noclick` command

`pip install "noclick[cli]"`, then `noclick login` (a browser approves it, and the key stays in your OS keychain),
`noclick agents chat`, `noclick bucket cp`, `noclick webhooks listen` and more: [The CLI](https://noclick.com/docs/guide/cli).

## Invite-only beta

These are open to accounts in the beta. [Request access](mailto:support@noclick.com?subject=Invite-only%20beta%20access); without it, a call answers 404 (`noclick.NotFound`), or
`noclick.NotAvailable`. The [reference](https://noclick.com/docs/reference/python) marks each one, parameters of
other calls included.

- [`noclick.Card`](https://noclick.com/docs/guide/cards): virtual cards with limits and approvals, for agents that buy things.
- [`noclick.Machine`](https://noclick.com/docs/guide/machines): an always-on machine at a flat monthly price for agents that never sleep (`machine=` on an agent).
- [Phone numbers](https://noclick.com/docs/guide/phone-numbers): the agent texting a caller (`texts=`, with US carrier registration), and moving a number in (`port_in`) or out (`transfer_out`).
- [`repo.checkout()`](https://noclick.com/docs/guide/repos): one of your repos in an agent's workspace (a GitHub connection's `checkout` works today).

## Development

```bash
cd sdk/python
pip install -e ".[dev]"
python -m pytest -q
```

## License

[Apache License 2.0](./LICENSE). The SDK is deliberately permissive so that the code you write against it
stays under whatever license you choose. NoClick itself is AGPL-3.0-only.
