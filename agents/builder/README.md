# NoClick's workflow builder

The agent that builds NoClick workflows from a description. It's an ordinary NoClick
agent: every action it takes is a call to NoClick's public API, the questions it asks are the questions any agent
asks, and it's made with the SDK from the definition in this folder. Nothing it does needs a private path, so you
can read it, run your own from your key, or change its instructions and tools.

```bash
pip install noclick
export NOCLICK_API_KEY=nk_live_...
cd agents/builder
python -m noclick_builder "Morning brief" "Every weekday at 8, email me today's calendar."
```

That makes the workflow when your account has none by that name, has the builder build it, and prints what it said
beside what the workflow itself says: its version, whether it's ready to run, and what's in the way.

## What it is

| File | What it holds |
| --- | --- |
| [`noclick_builder/definition.py`](noclick_builder/definition.py) | The agent: its name, its tools, the conversation a workflow's builds share, and the messages a build sends it. No dependency. |
| [`noclick_builder/INSTRUCTIONS.md`](noclick_builder/INSTRUCTIONS.md) | Its instructions: the steps of building a workflow, the API call each one makes, how steps fit together, and when to ask. |
| [`noclick_builder/agent.py`](noclick_builder/agent.py) | The builder made and run with the SDK: `ensure()` and `build()`. |

Its tools are three lines:

```python
owner = noclick.Human.owner()
tools = [
    noclick.Platform.only("read", "build", "deploy", "delete",                       # what it may do on NoClick
                          "workflows", "credentials", "humans", "secrets", "operations"),   # and where
    owner.only("notify", "ask"),                                                     # the account's owner
    "search", "fetch",                                                               # the web
]
```

`noclick.Platform` gives an agent NoClick's own API as tools: `api_describe` and `api_call` for any operation, and
`search` and `fetch` for the docs and the account's objects. The builder never spends: it holds no `spend`, so it
can't buy anything, and each call it makes is judged as any connected app's is.

## How a build goes

`build()` in [`agent.py`](noclick_builder/agent.py) is the whole loop:

1. Make the account's builder if it has none (`Agent.create(..., allow_existing=True)`).
2. Send it one message naming the workflow and what to do, in that workflow's own conversation
   (`build:<workflow id>`), so a later build reads what an earlier one asked and learned.
3. The builder works through the steps in its instructions: read the workflow's graph, find the step types, lay the
   graph out as one batch of edits, have NoClick's drafter fill each step in, fix what the answers name, attach the
   accounts that fit, test what's safe to run, and reply.
4. When it can't decide something, it asks the account's owner. Its turn waits, the question reaches them as any
   agent's does (a page, the chat's card, a text), and their answer starts its next turn. A question about which
   account a step uses attaches the account they pick.
5. Read the workflow's own facts: its version and its readiness. They're read from the workflow, never from the
   builder's reply, so a build can't claim more than is true.
6. If a step it left would fail at run time, send it back with exactly what fails, at most twice.

```python
import noclick
from noclick_builder import agent as builder

brief = noclick.Workflow.create("Morning brief")
built = builder.build(brief, "Every weekday at 8, email me today's calendar.")
print(built.summary)                                   # the builder's words
print(built.built, built.version, built.readiness)     # the workflow's facts

builder.build(brief, "Also post it to #team on Slack.", questions="assume")   # asks nothing
```

Follow it while it works, or read what it did afterwards, as with any agent:

```python
agent = builder.ensure()
for event in agent.watch(f"build:{brief.id}"):
    print(event.type, event.text or "")
for message in agent.history(f"build:{brief.id}"):
    print(message.role, message.text)
```

## Make it yours

- **Its instructions.** `builder.ensure(instructions=...)` makes it with your wording, and `agent.update(instructions=...)`
  changes one that exists. Start from `INSTRUCTIONS.md`.
- **Its tools.** Add a connection it should build with, or narrow `Platform.only(...)` further.
- **Its model and budget.** They're the agent's: `agent.update(model=..., budget_usd_per_month=...)`.

NoClick's hosted platform makes an account's builder from this same definition, for the accounts it has moved onto
it. NoClick tunes the wording of its instructions there; the tools, the loop and the facts are the ones here.

## Tests

```bash
pip install -e "../../sdk/python[dev]"
python -m pytest
```

They run against a mocked API, so they need no key.
