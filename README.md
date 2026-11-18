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
    <img src="docs/assets/hero-light.svg" alt="A loop of three scenes. On the left a Python file, app.py, imports noclick and acts as one of your users, little-rye; on the right is what its lines make happen. One: the code makes an agent named front-desk from the instructions in bakery.md, gets a phone number named front-desk in area code 415 for at most $5 a month, has the agent answer it, and prints +14155550142. A customer’s phone calls Little Rye Bakery on +1 (415) 555-0142; the call connects, and its record shows the caller asking “Do you bake the gluten-free loaf on Fridays?” and front-desk answering “Saturdays only. Shall I put one aside for you this Saturday?” Caption: A customer calls. The agent answers. Two: the code asks the person behind that user to approve “Refund Maya’s order?”, with the order, #1042, and the amount, $18.00, and waits. Their phone shows the approval page under the product’s name, Acme: Approval request, Refund Maya’s order?, Order #1042, Amount $18.00, a note field, Approve and Deny. They tap Approve, the page answers “Thanks, your answer was sent. You approved this.”, and the code prints True. Caption: A person says yes first. Three: the code asks noclick.estimate what an app on the edge at 100,000 requests a month, a SQLite database and a bucket would cost. An estimate appears with nothing made or charged: App on the edge $0.488, SQLite database $0.121, Bucket $0.096, $0.70 a month, which the code prints. It then copies a repository, makes it an app named little-rye and deploys it: a browser window says Building, then shows the bakery’s site live at little-rye.noclick.site, and the code prints https://little-rye.noclick.site. Caption: Priced first. Then live." width="830">
  </picture>
</p>

Every call in the loop is the Python SDK as this repository has it. The bakery, its customer and the product called Acme are made up; the estimate is what `noclick.estimate` answers for those three items today, each priced at what it costs NoClick with nothing added.

- **A number an agent answers.** `PhoneNumber.from_name(..., create_if_missing=True)` buys it, and `answer_with(agent)` sends its calls to the agent. [Phone numbers](https://noclick.com/docs/guide/phone-numbers)
- **A yes from a person.** `Human().approve(message, details=...)` sends them a page to answer on, and `.wait()` gives you `True` or `False`. [Asking people](https://noclick.com/docs/guide/humans)
- **A price before anything exists.** `noclick.estimate([...])` answers each charge and the month's total, and makes nothing. [Spend](https://noclick.com/docs/guide/spend)
- **An app at its own address.** `Repo.create(name, from_url=...)` copies a public repository, `Project.create(name, repo=repo)` makes it an app, and `deploy()` puts it live. [Apps and deployments](https://noclick.com/docs/guide/apps)

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
| `docs/assets` | The pictures in this README |
| `scripts/check.sh` | Builds and tests everything here, as CI does |

`scripts/check.sh` needs `python3`, Node 22.12 or later and pnpm 10 (`corepack enable pnpm`); CI runs it on
Python 3.12 and Node 22.

## Licence

Apache-2.0: see [LICENSE](LICENSE). Contributions are welcome ([CONTRIBUTING.md](CONTRIBUTING.md));
report a vulnerability as [SECURITY.md](SECURITY.md) says.
