<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/title-dark.svg">
    <img src="docs/assets/title-light.svg" alt="NoClick. The SDK for agent products. And the app built on it." width="620">
  </picture>
</p>

<p align="center">Your product acts for its own users: each of them gets hosted agents with their own inboxes, phone numbers and sandboxes, working in the accounts they connected and asking a person before anything risky. This repository is NoClick's SDKs for Python and TypeScript, both published as <code>noclick</code>, and the app built on them.</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/hero-dark.svg">
    <img src="docs/assets/hero-light.svg" alt="A loop of three scenes. On the left a Python file, app.py, imports noclick and acts as one of your users, little-rye; on the right is what its lines make happen. One: the code makes an agent named front-desk from the instructions in bakery.md, gets a phone number named front-desk in area code 415 for at most $5 a month, has the agent answer it, and prints +14155550142. A customer’s phone calls Little Rye Bakery on +1 (415) 555-0142; the call connects, and its record shows the caller asking “Do you bake the gluten-free loaf on Fridays?” and front-desk answering “Saturdays only. Shall I put one aside for you this Saturday?” Caption: A customer calls. The agent answers. Two: the code asks that user to connect Gmail, “to read the orders you get by email”, and waits. Their phone shows NoClick’s connect page under the product’s name, Acme: Connect Gmail; Acme asked you to connect Gmail for their NoClick automations, you don’t need a NoClick account; the reason; a Continue with Gmail button; Opens Google to sign in, NoClick never sees your password. They tap the button, the page says “Gmail is connected. Acme can use it now.”, and the code prints connected mara@littlerye.example. The code then gives the connection to front-desk as a tool and asks it “Any new orders?”: front-desk, in their Gmail, calls gmail.fetch_emails_from_inbox, which succeeds, and answers “Two new: 2 sourdough for Friday, 12 croissants for Saturday.”, which the code prints. Caption: They connect Gmail. The agent reads it. Three: the code asks the person behind that user to approve “Refund Maya’s order?”, with the order, #1042, and the amount, $18.00, and waits. Their phone shows the approval page under the product’s name, Acme: Approval request, Refund Maya’s order?, Order #1042, Amount $18.00, a note field, Approve and Deny. They tap Approve, the page answers “Thanks, your answer was sent. You approved this.”, and the code prints True. Caption: A person says yes first." width="830">
  </picture>
</p>

Every call in the loop is the Python SDK as this repository has it, and the connect page and the approval page are drawn after the ones NoClick shows a person. The bakery, its people and the product called Acme are made up.

- **A number an agent answers.** `PhoneNumber.from_name(..., create_if_missing=True)` buys it, and `answer_with(agent)` sends its calls to the agent. [Phone numbers](https://noclick.com/docs/guide/phone-numbers)
- **An account your user connects.** `Connection.from_name(..., create_if_missing=True, send_to="user")` sends them a page under your product's name, `wait()` returns once they have connected, and an agent with the connection in its `tools` works in their account. [Connections](https://noclick.com/docs/guide/connections)
- **A yes from a person.** `Human().approve(message, details=...)` sends them a page to answer on, and `.wait()` gives you `True` or `False`. [Asking people](https://noclick.com/docs/guide/humans)

## More of it, a few lines at a time

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/tour-inbox-dark.svg">
    <img src="docs/assets/tour-inbox-light.svg" alt="An inbox an agent answers. Seven lines of Python act as the user little-rye, get their agent front-desk and an inbox named orders at the address little-rye, answered by that agent, and print little-rye@noclick.email. Below, the inbox’s page: little-rye@noclick.email, An agent answers its mail, For Little Rye Bakery, one of your users, and no mail yet. A message arrives, Croissants for Saturday?, from Theo Marsh, theo@fennel.example: “Could you keep a dozen croissants for me on Saturday?” Then the inbox’s reply to him appears under it: “Yes. Twelve are set aside for you, from 7 on Saturday.”" width="405">
  </picture>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/tour-schedule-dark.svg">
    <img src="docs/assets/tour-schedule-light.svg" alt="A schedule that wakes an agent. Seven lines of Python make an agent named digest, told “You sum up the night’s orders.”, with one trigger: a noclick.Cron of 0 8 * * 1-5 in Europe/London, with the message Post the overnight summary. Below, the agent’s page: digest, Idle, Weekdays at 08:00, London time, Next run in 1m. The schedule fires: the agent is Working, its next run is tomorrow, and under Recent runs a run named Post the overnight summary is Running, then Succeeded, with its reply: “Seven orders came in overnight. Two are for pickup on Friday: answer those first.”" width="405">
  </picture>
</p>
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/tour-cap-dark.svg">
    <img src="docs/assets/tour-cap-light.svg" alt="A cap that stops the spend. Nine lines of Python set the user little-rye’s spend_cap_usd_per_month to 20, then, acting as that user, send their agent front-desk two messages and catch noclick.SpendCapExceeded on the second, printing its scope, spent and cap. Below, the user’s page: little-rye, This month $19.42 of $20. The first message, Write Friday’s menu, runs and succeeds, and the month turns red at $20.13 of $20, 101%. The second, Plan next week, is listed as Failed · spend cap, and the code prints user 20.13 20.0. Under the runs: The call that crosses a cap still finishes; the next one is refused." width="405">
  </picture>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/tour-deploy-dark.svg">
    <img src="docs/assets/tour-deploy-light.svg" alt="A price first. Then a live app. Twelve lines of Python ask noclick.estimate what an app on the edge at 100,000 requests a month, a SQLite database and a bucket would cost, print the month’s total, then copy a repository, make it an app named little-rye and deploy it, printing its address. Below, an estimate appears with nothing made or charged: App on the edge $0.488, SQLite database $0.121, Bucket $0.096, $0.70 a month, which the code prints. Then a browser window at little-rye.noclick.site says Building and shows the bakery’s site, Live, and the code prints https://little-rye.noclick.site." width="405">
  </picture>
</p>

The same made-up bakery and the same SDK, and under each snippet a page drawn after the one that shows it in NoClick. What the refused call prints is the [Spend](https://noclick.com/docs/guide/spend) guide's own example, and the estimate is what `noclick.estimate` answers for those three items today, each priced at what it costs NoClick with nothing added.

- **An inbox an agent answers.** `Inbox.from_name(..., create_if_missing=True, agent=agent)` opens an address, and each message that arrives wakes the agent, which replies on the thread. [Inboxes](https://noclick.com/docs/guide/inboxes)
- **A schedule that wakes an agent.** `noclick.Cron("0 8 * * 1-5", tz="Europe/London", message=...)` among an agent's `triggers` starts a turn each time it fires. [Triggers](https://noclick.com/docs/guide/triggers)
- **A cap that stops the spend.** `spend_cap_usd_per_month` on a user is checked before work starts; once it is used up, a call raises `noclick.SpendCapExceeded`, which names its `scope`, `spent` and `cap`. [Spend](https://noclick.com/docs/guide/spend)
- **A price first, then a live app.** `noclick.estimate([...])` answers each charge and the month's total, and makes nothing. `Repo.create(name, from_url=...)` copies a public repository, `Project.create(name, repo=repo)` makes it an app, and `deploy()` puts it live. [Apps and deployments](https://noclick.com/docs/guide/apps)

The SDK has the rest in the same shape: [sandboxes](https://noclick.com/docs/guide/sandboxes) and [browsers](https://noclick.com/docs/guide/browser) an agent works in, [channels](https://noclick.com/docs/guide/channels) where agents hand work to each other, [hosted MCP servers](https://noclick.com/docs/guide/mcp-servers), [queues](https://noclick.com/docs/guide/queues), [databases](https://noclick.com/docs/guide/databases) and [storage](https://noclick.com/docs/guide/storage).

## Start with one agent

You need a platform key with the scopes you use, in `NOCLICK_API_KEY`: the [developer console](https://noclick.com/dashboard/developers)'s API keys page makes one.

```bash
pip install noclick        # Python 3.10+
npm install noclick        # Node 20+, Bun, Deno, Cloudflare Workers
```

```python
import noclick

researcher = noclick.Agent.from_name(
    "researcher",
    create_if_missing=True,
    instructions="You research software vendors. Cite the pages you read.",
    tools=["exa.search"],
)
reply = researcher.message("What does Postmark charge for 100,000 emails a month?")
print(reply.text)
```

```ts
import { Agent } from "noclick";

const researcher = Agent.fromName("researcher", {
  createIfMissing: true,
  instructions: "You research software vendors. Cite the pages you read.",
  tools: ["exa.search"],
});
const reply = await researcher.message("What does Postmark charge for 100,000 emails a month?");
console.log(reply.text);
```

Each SDK's README has the full tour ([Python](sdk/python/README.md), [TypeScript](sdk/typescript/README.md)), [`sdk/examples`](sdk/examples) has complete programs, and the docs are at [noclick.com/docs](https://noclick.com/docs).

## The app, built on the same SDK

[`app`](app) is NoClick's own app, and it reaches NoClick only through the TypeScript SDK here. Run it with a NoClick key and it signs you in with a password of your own, keeps the key on its server, and opens on your account. That much is in this repository today:

<p align="center">
  <img src="docs/assets/app.webp" alt="Two pages of the app in this repository, side by side. Left, Sign in: “This app is private. Enter the password its owner set for it.”, a password field with a password typed, and a Sign in button. Right, the screen it opens on, for an account named Acme, dev@acme.test: Plan, Member; Left to spend, $41.37; Spent this month, $123.42 since September 1; and a Sign out button." width="760">
</p>

NoClick's screens are moving into it one at a time, the developer console first. These are that console and an app's page in Resources as they run on the SDK now, over sample data.

**Every agent: what it uses, and what it has spent.**

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/console-dark.webp">
    <img src="docs/assets/console-light.webp" alt="The developer console’s Home for an account named Acme, beside a sidebar of Home, Users, Resources, Logs, Usage and API keys. Under the title: 1 run going now, 1 failed in the last day, $123.42 spent this month. Then a table of six agents, each with its status, what it uses, the last day, this month’s spend and its activity: support-bot, idle, 1 turn failed, $33.05 of $50, active 3h ago; concierge for acme, working, 4 tools, $12.11, 1 turn running; assistant for 2 users, idle, $0.00; coder, idle, 1 tool, $0.00 of $20, active yesterday; reviewer for acme, idle, no tools, never ran; planner, working, $0.00 of $25, 1 turn running." width="830">
  </picture>
</p>

**Every run: what ran, what waited for a person, what a spending cap stopped.**

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/runs-dark.webp">
    <img src="docs/assets/runs-light.webp" alt="The console’s Logs: everything that ran, what each call did, and why anything failed. Tabs for Runs, Tool calls, API requests and Events, a filter over 10 runs, and the first seven of them, each with its status, summary, kind, source, when it was created, its wait and its duration: Running, an agent.message from concierge for acme, now, 20.4s; Succeeded, an agent.message from support-bot for acme, 12m ago; Succeeded, a sandbox.exec from backend-prod, 2.72s; Waiting · approval, a human.approve for user_42, waited 2h 0m; Failed · spend cap, an agent.message from support-bot for globex, 3h ago; Succeeded, Connect gmail, for user_42, waited 4m; Failed · interrupted, npm run build, a sandbox.exec, 1m 4s." width="830">
  </picture>
</p>

**An app live at its own address, with its domains and its requests.**

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/website-dark.webp">
    <img src="docs/assets/website-light.webp" alt="Resources, Websites, an app named booking: booking.noclick.site, Live, with Move to trash, Copy link and Open. Its address is booking.noclick.site, production is live, deployed Sep 26, 2026 from the branch main, on the edge runtime. One domain, acmebooking.com: the site is live at acmebooking.com and www.acmebooking.com. Requests over the last 7 days: 118,508, 19% more than the 7 days before, in a bar a day from Sep 20 to Sep 26, answered and failed." width="660">
  </picture>
</p>

## What is here

| Path | What it is |
| --- | --- |
| `sdk/python` | The Python SDK (Python 3.10+) |
| `sdk/typescript` | The TypeScript SDK (Node 20+, Bun, Deno, Cloudflare Workers), and `noclick/embed`, the bridge custom interface components use |
| `sdk/examples` | Complete programs on the Python SDK, each also a page at [noclick.com/docs/examples](https://noclick.com/docs/examples) |
| `app` | NoClick's app, built only on the TypeScript SDK: a React Router project that so far signs its owner in, keeps the NoClick key on its server and shows the account ([app/README.md](app/README.md)) |
| `plugins/noclick` | The Claude Code plugin for NoClick's hosted MCP server (`/plugin marketplace add noclickapp/noclick`); `.claude-plugin/marketplace.json` lists it |
| `glama.json` | This repository's listing in the Glama MCP directory |
| `docs/assets` | The pictures in this README; its `NOTICE.md` credits the icons and typefaces in them |
| `scripts/check.sh` | Builds and tests everything here, as CI does |

`scripts/check.sh` needs `python3`, Node 22.12 or later and pnpm 10 (`corepack enable pnpm`); CI runs it on
Python 3.12 and Node 22.

## Licence

Apache-2.0: see [LICENSE](LICENSE). Contributions are welcome ([CONTRIBUTING.md](CONTRIBUTING.md));
report a vulnerability as [SECURITY.md](SECURITY.md) says.
