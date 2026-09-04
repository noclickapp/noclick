# Agent Rehearsal

Running an agent for real, against a world that isn't.

## Why

Someone who has just connected their credentials has no idea whether the agent
will do anything sensible. Waiting for a real trigger to arrive is not an option
during onboarding — a support agent needs an angry customer, a personal
assistant needs a calendar conflict, and a new account has neither. So we stage
one.

The agent, the model, the prompt and the tool wiring are all real. Only the
world is fabricated.

## What it claims, and what it must never claim

A rehearsal proves **behaviour**. It proves nothing about **connectivity**.

That distinction is the whole reason this document exists. NoClick already has a
layer that proves connectivity — `connection_evidence` makes a real call and
shows the user their own channels or repos. If a rehearsal is allowed to read as
"it works", we have reinvented the green tick that layer was built to delete: a
confident-looking screen that a completely dead credential would also produce.

So the two ship together and are named differently:

| | proves | data |
|---|---|---|
| Connection evidence | the pipes are connected | real |
| Rehearsal | the judgment is sound | fabricated |

Every rehearsed step is labelled as rehearsed, in the trace, individually. A user
must never have to work out which half of the screen was real.

## Two modes

**Scripted** (this spec). Every tool call is intercepted and answered by a mock
model. Nothing outward happens. Works on an empty account, works with no
credentials attached at all.

**Live** (later). Real reads, writes held for approval. Strictly more convincing
where the account has data, and needs machinery scripted mode does not: a
read/write classifier, an approval gate, and a way to execute a held call after
the fact.

A single run is one mode or the other, never a blend. Mixing a real calendar
event with a fabricated email about something else produces incoherence that
reads as the agent being confused.

## Architecture

### The mock session

One model conversation per rehearsal, not one call per tool. This is the load-
bearing decision: because the session sees every tool call in order and
everything it has already returned, **its own context is the ledger**. An agent
that creates a ticket and reads it back gets the same ticket, because the mock
said so earlier and can see that it did. Cross-tool coherence comes from the same
place — one conversation, one fabricated world.

The alternative (independent generation per call, plus an explicit scenario
object and a side-effect ledger) was specced and dropped: it is strictly more
machinery for strictly less coherence.

Model: `openrouter/openai/gpt-oss-120b`, or `cerebras/gpt-oss-120b` where
available — generation is inline in the agent's turn, and Cerebras serves that
model fast enough not to be felt. Temperature low; the goal is plausible, not
creative.

Session state is keyed by `(workflow_id, execution_id)` and lives in Redis, not
process memory: CLI-harness tool calls arrive from a sandbox over the tool MCP endpoint
and may land in a different process than the one that started the run.

### Where it hooks

Two mirrors, exactly as per-tool **field scoping** already does — the codebase
maintains that pair for precisely this reason, because the two runtimes reach
tools by different routes:

- `nodes/agent/tool_execution.py` — beside `_enforce_field_scopes`. In-process
  SDK agent.
- `nodes/core/run_op.py` — beside `_check_field_scopes`. The path CLI-harness
  calls take over the tool MCP endpoint.

Hooking only one leaves the other route executing for real.

**Rehearsal is looked up, not threaded.** Field scopes ride in the per-tool
`info` dict because they are a property of the tool; a rehearsal is a property of
the *run*, and both mirrors already hold an identifier for it —
`run_node_op_tool` takes `conversation_id`, the in-process path has the execution
context. So the gate is a Redis lookup ("is this conversation rehearsing?"),
which needs no new parameter through the tool capability, the bundle, or the tool
config, and works cross-container for free.

It also fails safe in the right direction: `run_node_op_tool` is shared with the
hosted-MCP endpoint, whose calls carry their own `mcp-host:{id}` conversation and
therefore can never match a rehearsal key.

In scripted mode the interception is **total**: `run_node_operation` is never
reached, so no credential is resolved and no HTTP request is made. Safety is
structural, not a policy someone can forget to apply.

### Flow

```
template rehearsal block
   └── mocked trigger payload  ──►  agent turn begins (real agent, real model)
                                        │
                                        ├── tool call ──► mock session ──► JSON result
                                        ├── tool call ──► mock session ──► JSON result
                                        └── …
                                        ▼
                                    agent output
```

## Data

### Template rehearsal block

Authored by hand per template, shipped with it.

```jsonc
{
  "scenario": "A customer emails about a refund that never arrived. They ordered
               three weeks ago, were promised a refund eight days ago, and are
               angry but not abusive.",
  "trigger": {
    "node_id": "automation-gmail-...",
    "payload": { /* exact provider shape */ }
  }
}
```

**The trigger payload is hand-authored, never generated.** Trigger payloads have
exact provider shapes, and each node class translates them through
`resolve_agent_event` to build the agent's turn. A payload that is shaped
almost-right breaks that quietly: the agent receives a malformed event and
behaves oddly for reasons nothing on screen explains. Hand-authoring is also
where the template author stages the situation actually worth demonstrating.

`scenario` is prose, and it is the mock session's brief. It should describe the
world, not the desired outcome — writing "the agent should apologise and offer a
refund" produces a rehearsal that flatters the agent instead of testing it.

### Per tool call, sent to the mock session

- tool name and its description
- the arguments the agent actually passed
- the learned output schema for that `(node_type, operation)` from
  `workflow_node_output_schemas`

The arguments matter more than they look. A static fixture cannot answer
`search_tickets(query="refund not received")` sensibly; a session that sees the
query can. This is the difference between a rehearsal that demonstrates judgment
and one that demonstrates nothing.

### Mock session rules (system prompt)

1. Return only JSON matching the provided schema. Where a schema is supplied,
   constrain generation to it rather than trusting the model to comply.
2. Stay consistent with everything already returned in this session.
3. **Never fabricate a failure** unless the scenario scripts one. A rehearsal
   that randomly shows the agent handling an API error misrepresents its
   behaviour, and the user cannot tell the difference between a scripted failure
   and a mock model having a bad day.
4. Fabricate specifics — names, ids, timestamps, quantities. Placeholder-shaped
   output ("Example Customer", "lorem ipsum") reads as broken.

### Shape fidelity

`workflow_node_output_schemas` learns output schemas from real executions, keyed
by `(node_type, node_operation)` — roughly 292 pairs observed, concentrated on
exactly the operations templates use. Where a schema exists it is a hard
constraint on generation.

Where one does not exist the model improvises the shape, and the failure is
**silent**: the agent reasons over a plausible-looking object with the wrong
field names, and any `{{ }}` reference downstream resolves to nothing. Before
shipping a template, check that every operation its agent can reach has an
observed schema. This is the largest residual risk in the design.

## Invariants

- No credential is resolved and no provider request is made. If a rehearsal ever
  reaches `run_node_operation`, that is a bug, not a degraded mode.
- Every rehearsed step is labelled individually in the trace.
- A rehearsal never writes to `cas_manifests`, never counts as an execution, and
  never satisfies "this workflow has run successfully".
- Mocked content enters the real agent's context, so a template's `scenario` is
  trusted input. Fine while templates are ours; revisit before they are
  user-authored.
- **Graph scope is real-delivery scope.** The run dispatches with
  `start_node_id` = the staged trigger, so only its reachable subgraph runs
  (providers backfilled) — a whole-canvas run executed every parentless node as
  a start node. Within that subgraph, GRAPH nodes are a separate execution path
  from tool calls, so `rehearsal_excluded_node_types()` (every credentialed
  type + the credential-less external actors: send-email, http-request, nested
  workflows) is gated in TWO mirrors: the concurrent runner skips them visibly,
  `_execute_node` raises for bypassing callers (iteration bodies). Agents,
  providers, interface/state nodes and pure compute keep executing —
  trigger→transform→agent is a real shape.
- **Only stageable triggers are offered, and wiring decides — not type
  presence** (`can_stage_trigger`): a provider-wired node is the agent's tool
  (the runner drops trigger payloads landing on it), and a node from which no
  agent is reachable stages an event with no story. `resolve_trigger_node_id`
  applies the same filter, so a provider-wired sibling never swallows the event.
- **Anonymous template-page runs pin every agent to the platform default SDK
  model** (`rehearsal_launch.public_model_pin`, applied only when
  `public=True`): CLI harnesses are strict-BYOK with no platform key injection,
  and the template owner ships no harness credential — respecting the
  template's harness sent a keyless codex turn to OpenAI (401, 2026-08-12).
  Only `openrouter/*` SDK models run credential-free and cost-captured, so
  harnesses and direct-provider SDK models pin; media agents and
  already-openrouter agents keep their config. In-product rehearsals never
  pin — the user's real harness is part of what they're testing.
- **The rehearsal's conversation key beats the event's.** A staged event's
  `conversation_key` is the FIXTURE'S chat id; adopting it would persist
  fabricated history where a real chat with that id resumes, and interleave
  repeat runs of one scenario (`effective_conversation_key`). On real
  deliveries the event key keeps winning — the channels story depends on it.

## Failure handling

If the mock session itself fails — unreachable, malformed output, schema
violation it cannot satisfy — the rehearsal **stops and says so**. It does not
fall back to returning `{}` to the agent, which would produce a confident,
plausible, entirely misleading trace of an agent reasoning over nothing.

## Interface

The step already has the right vocabulary (`DryRunPhase` in the onboarding
route): a scenario card, a trace of what it did, the composed artifact, and a
CTA. What it needs is for all of it to be real, and for the rehearsed nature to
be legible without being apologetic.

- **The scenario** reads as a situation, not as configuration. It is the setup
  for everything below it and should be the first thing understood.
- **The trace** streams live through the existing `agentic_steps` frames —
  `tool_step_event` / `tool_call_step_text`, consumed by `useAgentChat`'s
  `advanceSteps`. This is the anti-dead-air device and it is independently
  persuasive: watching it read the ticket, search the docs, then draft the reply
  is most of the convincing.
- **Rehearsed marking** is per step, quiet, and consistent — one treatment, used
  everywhere, never omitted on a step because it looked cluttered.
- **The artifact** renders natively. A Slack briefing looks like a Slack message;
  an email looks like an email. Not JSON, not a log line.
- **The CTA** is honest about what just happened: this is what it would do, and
  the next step makes it real.

Visual direction is iterated in `/design/onboarding/guided` against the live
implementation, not mocked separately.

## Build order

1. Mock session: Redis-backed, one conversation per rehearsal, schema-constrained
   generation.
2. Interception at both mirrors, with the session id carried on the existing
   `tool_ctx` channel.
3. Template rehearsal block, authored for one template end to end.
4. Interface, iterated live.
