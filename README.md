# NoClick

NoClick's SDKs for Python and TypeScript, both published as `noclick` (on PyPI and npm), the
example programs built on them, and the start of the app built on them (`app`).

With the SDKs, your product acts for its own users on NoClick's hosted platform: connect their
accounts, give your LLM tools, reach a person for an answer or an approval, and run hosted agents
with their own inboxes, phone numbers and sandboxes. The docs are at
[noclick.com/docs](https://noclick.com/docs).

## Quickstart

You need a platform key with the scopes you use, in `NOCLICK_API_KEY`.

### Python

```bash
pip install noclick
export NOCLICK_API_KEY=nk_live_...
```

```python
import noclick

researcher = noclick.Agent.from_name(
    "researcher",
    create_if_missing=True,
    instructions="You research software vendors. Cite the pages you read.",
    tools=["exa.search"],
)
print(researcher.message("What does Postmark charge for 100,000 emails a month?").text)
```

### TypeScript

```bash
npm install noclick
export NOCLICK_API_KEY=nk_live_...
```

```ts
import { Agent } from "noclick";

const researcher = Agent.fromName("researcher", {
  createIfMissing: true,
  instructions: "You research software vendors. Cite the pages you read.",
  tools: ["exa.search"],
});
console.log((await researcher.message("What does Postmark charge for 100,000 emails a month?")).text);
```

Each SDK's README has the full tour: [Python](sdk/python/README.md), [TypeScript](sdk/typescript/README.md).

## Layout

| Path | What it is |
| --- | --- |
| `sdk/python` | The Python SDK (Python 3.10+) |
| `sdk/typescript` | The TypeScript SDK (Node 20+, Bun, Deno, Cloudflare Workers), and `noclick/embed`, the bridge custom interface components use |
| `sdk/examples` | Complete programs on the Python SDK, each also a page at [noclick.com/docs/examples](https://noclick.com/docs/examples) |
| `app` | NoClick's app, built only on the TypeScript SDK. So far it is the app's shell, a React Router project with one page; NoClick's screens move into it one at a time ([app/README.md](app/README.md)) |
| `plugins/noclick` | The Claude Code plugin for NoClick's hosted MCP server (`/plugin marketplace add noclickapp/noclick`); `.claude-plugin/marketplace.json` lists it |
| `glama.json` | This repository's listing in the Glama MCP directory |
| `scripts/check.sh` | Builds and tests everything here, as CI does |

`scripts/check.sh` needs `python3`, Node 22.12 or later and pnpm 10 (`corepack enable pnpm`); CI runs it on
Python 3.12 and Node 22.

## History

Until November 2026 this repository held NoClick's self-hosted workflow engine. That code is no longer
updated. It remains in this repository's history, under the licence it was published with (AGPL-3.0):
its last commit is [`ee0da77`](https://github.com/noclickapp/noclick/tree/ee0da77f444f2b59d68b65845415240eca68de4a)
and its last release [v0.4.2](https://github.com/noclickapp/noclick/releases/tag/v0.4.2).

## Licence

Apache-2.0: see [LICENSE](LICENSE). Contributions are welcome ([CONTRIBUTING.md](CONTRIBUTING.md));
report a vulnerability as [SECURITY.md](SECURITY.md) says.
