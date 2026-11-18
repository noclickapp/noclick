# noclick

TypeScript client for the NoClick Platform API: act for your own users (the people and
companies your product serves, keyed by your own ids), connect their accounts, give your LLM tools, reach a human, run hosted agents,
and give them inboxes, phone numbers and sandboxes.
The same SDK as the Python `noclick`: same nouns, verbs, errors, user scoping and
retries, in camelCase and async-only. It works with NoClick's hosted platform.
From 0.2 the `noclick` package is this client; the workflow client it replaces stays at 0.1.x, and the
bridge custom interface components use is its `noclick/embed` entry (below).

No runtime dependencies: it runs on the global `fetch` and Web Crypto, so Node 20+, Bun, Deno and
Cloudflare Workers all work (`asUser` needs `AsyncLocalStorage`: on Workers, enable
`nodejs_compat`).

```bash
npm install noclick
export NOCLICK_API_KEY=nk_live_...     # a platform key with the scopes you need
# NOCLICK_API_URL defaults to https://api.noclick.com
```

## Quick tour

```ts
import { Agent, Connection, User, asUser } from "noclick";

const user = User.fromId("user_42", { createIfMissing: true, email: "ana@example.com" });   // your own id for Ana

await asUser(user, async () => {
  // A named connection: pending until Ana connects her Gmail at connectUrl
  const gmail = await Connection.fromName("gmail", { integration: "gmail", createIfMissing: true, redirectUrl: "https://acme.ai/done" }).hydrate();
  console.log(gmail.connectUrl);               // send your user here
  await gmail.wait();                          // resolves once they've connected

  const approval = await user.human.approve("Send the weekly summary to your team?");
  const ok = await approval.wait();            // true / false

  // Ana's own agent: acts in her connections; may ask her for a calendar when it needs one
  const assistant = Agent.fromName("assistant", {
    createIfMissing: true, instructions: "You run Ana's day.", tools: [gmail, "search"], canRequest: ["google_calendar"],
  });
  console.log((await assistant.message("What's on today?")).text);
});
```

## Ideas

- **Lazy objects.** `User.fromId(...)`, `Connection.fromName(...)`, `Agent.fromName(...)`,
  `Operation.fromId(...)` send nothing until used; `createIfMissing` creates on first use (a
  concurrent create is adopted, not duplicated). Methods load the object themselves; `await
  obj.hydrate()` loads it explicitly, and reading a property the lazy reference can't answer yet
  throws. Given fields, `Agent.fromName` (and the others that take them) sets them on the one it finds,
  on every run, with or without `createIfMissing`: one you leave out is never changed, one it can't set
  on an existing agent, like `ttlS`, throws `Conflict`, and the grants its user gave the agent are kept.
  `create(..., { allowExisting: true })` makes one once and returns it untouched after.
- **Named connections.** Code, toolkits and agents name a connection (`"gmail"`, or a
  `Connection`), so they always act in exactly that account; two accounts on one service are two
  names. An agent's connections are its own scope's: a user's agent uses the user's, an account
  agent the account's. A connection also says what its service can do: `connection.operations()`,
  `connection.operation(name)` and `connection.events()` read the catalog, without loading the
  connection when it was named with its `integration`; `Connection.integrations(query)` finds a
  service to connect. An operation whose `needsAccount` is false (web search on `exa`, say) needs no
  connection: a name that is no connection in the scope names an integration's account-free
  operations, so `tools: ["exa.search"]` and `run("exa.search", { ... })` work for every user with
  nothing connected, on NoClick's key. A connection named `exa` holding your own key takes over the
  same refs, and a pending connection still runs those operations on NoClick's key.
- **Users.** A user's id is your own id for them: 1 to 255 printable ASCII characters, no spaces or
  `/`, and not `all` or `none` (the list filters); an id that breaks a rule throws
  `InvalidRequest` before anything is sent. `user.update({ id: "new_id" })` renames one, and
  everything it owns follows. `await asUser(userOrId, async () => ...)` (or `client.asUser`)
  scopes every call inside it through `AsyncLocalStorage`, so concurrent requests never see each
  other's user. Every method's `{ user }` option wins; `user: null` means the account. The id is
  sent as it is, in the `NoClick-User` header. Objects a user owns (its connections, agents,
  channels, sandboxes) always act for that user; shared objects (`Toolkit`, `new Human()`,
  account-level agents) follow the user current at each call. Catalog reads
  (`Connection.integrations()`, `connection.operations()`) carry no user.
- **Operations.** Anything that waits on the world returns an `Operation<T>`; `await op.wait({ timeoutS })`
  long-polls and resolves to the typed outcome (`Connection`, `Answer`, `boolean`, `AgentReply`) or
  throws the typed error. `op.events()` is an async iterator of status changes; `op.cancel()` cancels.
- **Errors** extend `NoClickError` with `type`, `message`, `nextStep`, `details` (the wire's extra
  keys, snake_case), `status` and `requestId`: `NeedsConnection` and `CredentialDisconnected` have
  `connection` and `connectUrl`, `Conflict.existingId`,
  `SpendCapExceeded.cap/spent/scope`, `PaymentRequired.balanceUsd/requiredUsd` (dollars),
  `ApprovalRequired.approvalId/approveUrl/operationId`, `RateLimited.retryAfter`, plus `PolicyDenied`, `PermissionDenied`,
  `NotFound`, `Expired`, `InvalidRequest`, `APIConnectionError`, `OperationTimeout`, ...
- **Safe retries.** 408/429/5xx and network errors retry with backoff (honouring `Retry-After`);
  `quota_exceeded` never retries. Each write carries one `Idempotency-Key` for all its attempts;
  a POST's 500 is not retried, nor an answer the server replays for that key (`Idempotent-Replayed`);
  an error says how many times the call was sent (`err.attempts`).
- **Units.** Durations that map to the API are seconds, named like the wire (`timeoutS`,
  `expiresInS`, `ttlS`, `waitS`); only the transport's own settings are milliseconds (`timeoutMs`).

## Tools for your LLM

```ts
import Anthropic from "@anthropic-ai/sdk";
import { Toolkit, asUser } from "noclick";

const toolkit = new Toolkit(["gmail", "search"]);   // build once; it follows the current user
await asUser("user_42", async () => {
  const messages: Anthropic.MessageParam[] = [{ role: "user", content: "Email Ana the lemon cake recipe" }];
  for (;;) {
    const response = await anthropic.messages.create({ model, max_tokens: 1024, tools: await toolkit.definitions(), messages });
    if (response.stop_reason !== "tool_use") break;
    messages.push({ role: "assistant", content: response.content },
                  { role: "user", content: await toolkit.handle(response) });
  }
});
```

OpenAI: `await toolkit.definitions({ format: "openai" })` and
`messages.push(...await toolkit.handleOpenAI(completion))` (Responses API `function_call` items work
too). Connection tools are named `{connection}__{operation}`. A tool whose connection has no
account yet returns a normal result telling the model so, with the link; `toolkit.call(...)`
exposes it as `result.needsConnection` / `result.connectUrl`.

A tool call never throws for policy: a denied call, or one held for approval, comes back as an
error result the model reads. A hold's details are kept out of the model's view, in
`result.approvalRequired` (`approval_id`, `request_id`, `approve_url`, `operation`, `approver`:
`"user"` or `"owner"`). `request_id` (the request a person answers), `approve_url` and `operation`
(the approval's operation object) are `null` unless the request is addressed to you; the approver is
emailed either way. The handle helpers pass each held call to `onApproval`:

```ts
await toolkit.handle(response, { onApproval: (r) => notify(r.approvalRequired) });
```

Once the person approves, the model's retry of the identical call goes through.

No model key of your own? `AI` runs chat, embeddings, images and transcription paid from your
NoClick balance, and `AI.baseUrl` is an OpenAI-compatible endpoint (chat completions, responses,
embeddings, models) for any OpenAI client, where your agents are models too:

```ts
const reply = await AI.chat(messages, { tools: await toolkit.definitions({ format: "openai" }) });
const answer = await AI.chat("Where's my refund?", { model: "agent:support" }); // conversation: answer.conversation continues it
```

## More

```ts
const slack = Connection.fromName("slack", { user: "user_42" });
await slack.lookup("channel", { search: "gen" });                             // options for an ID field
await gmail.run("send_email_message", { to: ["a@b.c"], subject: "Hi", body: "..." });
const services = await Connection.integrations("mail");                      // name, label, connectWith, operationCount
for (const op of await slack.operations({ search: "message" })) console.log(op.name, op.needsAccount, op.parameters);
await slack.operation("send_message");                                        // one, with its JSON-schema parameters; NotFound otherwise
await run("exa.search", { query: "..." });                                    // needs no account: no connection, NoClick's key
await run("gmail.send_email_message", { to: ["a@b.c"] }, { user: "user_42" }); // the same ref runs through a connection named gmail
await (await gmail.request({ reason: "to send your summaries" })).wait();      // emails a fresh link to the user
await gmail.token();                                                          // OAuth only, credentials:token scope
await Connection.create("crm", { credentialType: "affinity_api_key", data: { api_key: "..." } });   // a key you hold
for (const grant of await assistant.grants()) console.log(grant.connection, grant.status);  // assistant.revokeGrant(grant)
const reply = await agent.message("Any lemon cake?");
await agent.message("Two slices please", { conversation: reply.conversation ?? undefined });
await agent.wake("orders", { note: "Check the order shipped.", afterS: 3600 });   // a turn later; agent.wakeups(), its wake_me tool
await agent.memory.save("menu", "Lemon cake on Fridays.", { description: "What we bake when" });   // it sees the line every turn
const researcher = await agent.spawn("Find three launches.", { conversation: "launch", updates: ["blocked", new Every(900)] });
await researcher.job!.wait(); await researcher.ask("Where are you?");          // agent.jobs(); job.updates(); ask({ interject: true })
await Agent.create("coder", { instructions: "...", harness: "claude_code", modelConnection: "claude" });   // Agent.harnesses() lists them

await Policy.set({ deny: ["*.delete_*"], requireApproval: ["gmail.send_email_message"] }, { user: "user_42" });
await Brand.set({ name: "Acme", color: "#0f766e", emailFromName: "Acme" });
const month = await usage({ groupBy: "user" });                            // month.get(user.id)
const est = await estimate([{ kind: "project", runtime: "edge", usage: { requests: 100_000 } }, { kind: "bucket" }]);
console.log(est.monthlyUsd, est.lines);                                     // priced before anything is made; nothing is charged

const channel = await Channel.create("orders", { members: [agent, "user"], mode: "mentions" });
await channel.post("@sunrise-host what's on today?", { as: "user" });
for await (const message of channel.stream()) console.log(message.author.name, message.text);

const sandbox = await Sandbox.create({ image: "python" });
await sandbox.files.write("main.py", "print(1 + 2)");
console.log((await sandbox.exec("python main.py")).stdout);
await sandbox.terminate();

const run = await (await Workflow.fromName("order-intake").run({ order_id: "o1" })).wait();   // one built in the app
console.log(run.outputs);

const client = new NoClick({ apiKey: "nk_live_other", baseUrl: "https://api.noclick.com" });
await User.list({ client });                                                // or configure({ apiKey })
```

## Sessions, inboxes and phone numbers

```ts
// User sessions: a short-lived token pinned to one user, safe for a browser
const session = await user.session({ scopes: ["agents", "humans", "inbox"], ttlS: 3600 }); // max 24h
res.json({ token: session.token });                 // console.log / inspect never show the token
const userClient = NoClick.forSession(session);   // same as new NoClick({ apiKey: session.token })
await Agent.list({ client: userClient });         // acts as that user, with those scopes only

// Agents can search and fetch; every agent can also run shell commands (a policy can deny `code`)
await Agent.create("researcher", { instructions: "...", tools: ["search", "fetch", gmail] });

// Channels: list them; remote A2A agents can carry auth headers (stored encrypted, never shown back)
await Channel.list({ status: "open", limit: 20 });
await channel.add(new A2AMember("https://remote.ai/a2a", { headers: { Authorization: "Bearer ..." } }));
channel.members[0].a2aHeaderNames;                  // ["Authorization"]: names only

// Triggers and subscriptions: a URL or an app's events wake an agent, or post in a room as the app
const orders = await agent.addTrigger(new OnWebhook("orders", { message: "A new order arrived." }));
console.log(orders.url);                            // each POST is a turn
await agent.addTrigger(new OnEvent("slack", "app_mention"));   // slack.events() lists the events
await channel.subscribe(new OnEvent("stripe", "invoice_payment_failed"), { wake: [agent] });

// Workspaces: a company's channels, agents and people under one name, with a monthly cap
const ana = User.fromId("ana");
const acme = Workspace.fromName("Acme", { createIfMissing: true, members: [agent, ana], budgetUsdPerMonth: 200 });
const billing = await Channel.create("billing", { workspace: acme, members: [agent, ana] });
await billing.post("Can we refund order 42?", { as: ana });   // each person as themselves
await acme.subscribe(new OnWebhook("deploys"), { channels: "all", wake: "all" });   // one source, every room

// Inboxes: an address your code or agent receives mail at
const inbox = await Inbox.create({ localPart: "signup", agent: "agt_..." });   // agent wakes per message
const mail = await (await inbox.waitFor({ sender: "noreply@github.com", subjectContains: "code", timeoutS: 300 })).wait();
console.log(inbox.address, mail.text, mail.attachments);
await mail.reply("Thanks!");                        // to the sender only; no free-form outbound
for await (const message of inbox.stream()) console.log(message.subject);   // a listing may trim bodies: await message.refresh()

// Phone numbers (US local, monthly; NotAvailable outside the phone feature)
const [pick] = await PhoneNumber.available({ areaCode: "415", limit: 1 });
const number = await PhoneNumber.buy(pick, { maxMonthlyUsd: 5 });   // PriceExceeded above the ceiling
await number.answerWith(agent);
const call = await (await number.call("+14155550100", { goal: "Confirm Friday's 3pm booking." })).wait();
console.log(call.text, call.seconds, call.costUsd);  // call.transcript: [{ role, text, at }, ...]

// Sandboxes: long commands in the background, within the sandbox's own lifetime
const box = await Sandbox.create({ timeoutS: 3600 });
const build = await box.exec("make all", { background: true, timeoutS: 1800 });  // Operation<ExecResult>, up to 3600s
console.log((await build.wait()).exitCode);

// Volumes: a folder that outlives the sandbox or turn that wrote it; buckets: files by key with signed links
const data = Volume.fromName("datasets", { createIfMissing: true });
await data.write("/raw/orders.csv", "id,total\no_1,42\n");
const withData = await Sandbox.create({ volumes: { "/data": data } });
const uploads = Bucket.fromName("uploads", { createIfMissing: true });
await uploads.put("invoices/0042.pdf", "%PDF-1.7 ...");
console.log(await uploads.signedUrl("invoices/0042.pdf", { expiresIn: 3600 }));

// Secrets: write-only values in a sandbox's or an agent's shell environment
const shipping = Secret.fromName("shipping", { values: { SHIPPING_API_KEY: "sk-..." }, createIfMissing: true });
const withKey = await Sandbox.create({ secrets: [shipping], network: true });

// Dicts: shared key-value state; queues: work delivered at least once, to code or to an agent
const seen = Dict.fromName("processed-orders", { createIfMissing: true });
if (await seen.putIfAbsent("evt_9f2c", true, { ttlS: 7 * 86400 })) console.log(await seen.increment("handled-today"));
const jobs = Queue.fromName("invoices", { createIfMissing: true });
await jobs.put({ invoice: "INV-1042" }, { dedupeKey: "INV-1042" });
const chaser = Agent.fromName("chaser", { createIfMissing: true, instructions: "Chase unpaid invoices.",
  triggers: [new OnQueue(jobs)] });   // each message a turn, one at a time

// Regions: where a sandbox or an agent runs, for good (else your account's default)
console.log((await regions()).map((r) => r.name));          // ["us-east", "us-west", "eu", "ap", "in"]
const near = await Sandbox.create({ region: agent.region ?? undefined });

// Hosted MCP servers: a user's tools at one URL, for Claude, ChatGPT or Cursor
const server = McpServer.fromName("crm-tools", { tools: ["hubspot", "search"], createIfMissing: true, user: "acme" });
console.log((await server.hydrate()).url, server.toolCount, (await server.clients()).map((c) => c.name));

// Repos: a copy of a public git repository, history and all (wait() gives the Repo once it's copied)
const blog = await (await Repo.create("blog", { fromUrl: "https://github.com/acme/blog" })).wait();

// A repository in a coding agent's workspace; NoClick refuses a push outside agent/*
const github = Connection.fromName("github", { integration: "github", createIfMissing: true });
const fixer = Agent.fromName("fixer", {
  createIfMissing: true, instructions: "Fix the failing tests.", harness: "claude_code", modelConnection: "claude",
  repos: [github.checkout("acme/web", { push: "agent/*" })],
});
```

A policy `requireApproval` match makes `connection.run` throw `ApprovalRequired`; the approval
request is already out. `await err.operation?.wait()` resolves `true` once approved, then retry the
same call with `{ approvalId: err.approvalId }`. A `Toolkit` never throws for policy (see "Tools for
your LLM"). Policy and Brand are account administration: they never follow `asUser`, only an
explicit `{ user }`.

## Activity: operations, tool calls, requests, usage

```ts
// Pages: list() drains; listPage() returns one page and its cursor (every resource with a list)
const page = await Operation.listPage({ kind: "agent.message", status: "live", limit: 50 });
await Operation.listPage({ kind: "agent.message", status: "live", cursor: page.nextCursor });

// Read across users without acting as one: userFilter is the user_id query, never the header
await Agent.list({ userFilter: ALL_USERS });              // NO_USER = account-level only
await Agent.list({ status: "working", order: "last_active" });   // each: status, lastActiveAt, runningTurns, childCount
await Sandbox.listPage({ userFilter: "user_42" });          // a User or your id for one

await Operation.list({ status: "failed", createdAfter: new Date(Date.now() - 86_400_000) });
(await Operation.summary({ kind: "agent.message", agent })).byStatus;   // { running: 1, ... }
const op = Operation.fromId("…");
await op.hydrate(); op.waitMs; op.runMs; op.heldMs; op.transitions; await op.toolCalls();
console.log(op);   // on the hosted API: Operation { ..., consoleUrl: "https://noclick.com/dashboard/developers/operations?op=…" }
// errors thrown by op.wait() end with the same console link

await ToolCall.listPage({ tool: "gmail.*", status: "error", source: "agent" });
await ToolCall.summary({ since });                            // total, success, error
await ApiRequest.listPage({ method: "POST", status: "4xx", key: "nk_live_ab12" });   // writes and failures
await HumanRequest.listPage({ status: "pending", kind: "approve" });
await agent.conversationsPage({ userFilter: ALL_USERS });   // a user's own agent: owner sessions only (a key 404s; drop the filter)
await Usage.series({ groupBy: "agent" });                     // daily lines this month; Usage.limits() for caps
await Policy.evaluate(["gmail.send_email_message"], { draft: { layer: "account", deny: ["gmail.*"] } });
await Policy.list(); await Brand.reset();

// apiKey may be a function, asked on every attempt: a refreshing token
new NoClick({ apiKey: async () => (await session()).accessToken });

// Events, delivered to your server signed (Webhook.verify in your receiver), kept 30 days
const hook = Webhook.fromName("https://api.yourco.test/noclick/events", { createIfMissing: true, events: ["operation.failed", "connection.*"] });
await Event.list({ type: "operation.failed", userFilter: ALL_USERS, limit: 20 });
await agent.wake("launch", { when: "connection.connected", filters: { name: "gmail" }, note: "Gmail is in: carry on." });
await agent.addTrigger(new OnPlatformEvent("operation.failed", { filters: { kind: "agent.task" } }));
await channel.subscribe("connection.disconnected");

// Charging your users: usage.recorded per step of their spend; pause them, in your words, when your billing says
const user = User.fromId("user_42");
await user.pauseSpending({ message: "You've used your credits.", action: { label: "Top up", url: "https://acme.test/top-up?u={{user.id}}" } });
await user.resumeSpending();                                  // what they sent meanwhile runs now
await User.list({ spending: "paused" });
```

## Invite-only beta

These are open to accounts in the beta. [Request access](mailto:support@noclick.com?subject=Invite-only%20beta%20access); without it, a call rejects with a 404 (`NotFound`), or
`NotAvailable`. The [reference](https://noclick.com/docs/reference/typescript) marks each one, parameters of other
calls included.

- [`Card`](https://noclick.com/docs/guide/cards): virtual cards with limits and approvals, for agents that buy things.
- [`Machine`](https://noclick.com/docs/guide/machines): an always-on machine at a flat monthly price for agents that never sleep (`machine` on an agent).
- [Phone numbers](https://noclick.com/docs/guide/phone-numbers): the agent texting a caller (`texts`, with US carrier registration), and moving a number in (`portIn`) or out (`transferOut`).
- [`repo.checkout()`](https://noclick.com/docs/guide/repos): one of your repos in an agent's workspace (a GitHub connection's `checkout` works today).

## The CLI

[The `noclick` command](https://noclick.com/docs/guide/cli) comes with the Python package (`pip install "noclick[cli]"`).

## Custom interface components: `noclick/embed`

A custom interface component on a NoClick canvas runs in a sandboxed iframe and talks to the workflow it
belongs to through the bridge: its inputs, any node's output, running nodes and streaming their output,
state, files and datasets. Inside the canvas it is imported as `@noclick/sdk` and initialises itself over
`postMessage`, with no key. The same API is the package's `noclick/embed` entry, and `init({ apiKey })` reaches a
workflow from outside the canvas over the instance's socket API, a self-hosted one included (`url:`).

```ts
import { execution, useInputs } from "noclick/embed";
```

Outside the canvas it needs `react` (and `socket.io-client` for the socket API) installed beside it; the
client above needs neither.

Its design is in [`src/embed/DESIGN.md`](./src/embed/DESIGN.md).

## Development

```bash
cd sdk/typescript
npm ci
npm test            # the client (Node >= 22.6 test runner, native type stripping, fetch mocked) and the bridge (vitest)
npm run typecheck   # the client's src without Node types; its tests with them
node build.js       # dist/index.js and dist/types/ (the client), dist/sdk.esm.js (the bridge)
```

Source files import each other with `.ts` extensions so Node, Bun and Deno run them directly; the build
bundles them and rewrites the declarations' imports to `.js`.

## License

[Apache License 2.0](./LICENSE). The SDK is deliberately permissive so that the code you write against it
stays under whatever license you choose. NoClick itself is AGPL-3.0-only.
