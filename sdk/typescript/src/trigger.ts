/**
 * Triggers: what wakes an agent besides a message.
 *
 *     const fulfilment = Agent.fromName("fulfilment", {
 *       createIfMissing: true,
 *       instructions: "You confirm new orders with the customer.",
 *       triggers: [new OnWebhook("orders", { message: "A new order arrived." })],
 *     });
 *
 * An `OnWebhook` gives it a URL whose POST body is the turn, an `OnEvent` subscribes it to a
 * connection's app events, an `OnPlatformEvent` to NoClick's own events (an operation failing, a
 * connection breaking), and a `Cron` wakes it on a schedule (an agent with one is an automation).
 * An `OnQueue` makes each message on a queue a turn. Mail and calls wake it too, set up where they
 * live (`Inbox.create({ agent })`, `PhoneNumber.answerWith`); `triggers()` lists them as kinds `email`
 * and `call`, and while its policy may hold one of its tools for a person, as kind `approval`: an
 * answered approval wakes it in the held call's conversation. A webhook, app event or queue trigger takes `conversation`, a template over what arrived
 * (`"issue-{issue.number}"`): deliveries that render the same key continue one conversation, recorded
 * as the turn's `input.conversation`.
 */

import { Connection } from "./connection.ts";
import type { Cron } from "./cron.ts";
import { compact, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";
import { Queue } from "./queue.ts";

/**
 * A URL that wakes the agent: each POST to it is a turn, its body the message (a JSON body is
 * passed as JSON). The URL is `AgentTrigger.url`; anyone who has it can wake the agent, so keep it
 * like a key. It stays the same while a trigger of that `name` stays on the agent. `message` is
 * what the agent is told with every delivery, above the body.
 */
export class OnWebhook {
  readonly name: string;
  readonly message: string | null;
  /** The conversation a delivery continues: a template over its body; a `NoClick-Conversation` header wins. */
  readonly conversation: string | null;

  constructor(name: string, options: { message?: string; conversation?: string } = {}) {
    this.name = name;
    this.message = options.message ?? null;
    this.conversation = options.conversation ?? null;
  }

  /** @internal */
  toWire(): JsonObject {
    return { kind: "webhook", name: this.name, ...compact({ message: this.message, conversation: this.conversation }) };
  }
}

/**
 * An app event from one of the agent's connections, such as a Slack message or a new HubSpot
 * contact. `connection` is a `Connection` or its name, looked up for the agent's own user (an account agent's may be
 * one connected in the app, `credential:<id>`); `event` names one
 * of the integration's app events (`channel_message` for Slack, `contact_created` for HubSpot; `connection.events()`
 * lists them) and `filters` narrow it the way the integration takes them, like `{ channel: "C0123ABCD" }` (a Slack
 * channel's id: `slack.lookup("channel")`). `message` is what the agent is told with every event, above it. A thread
 * (a Slack thread) stays one conversation. The connection needn't be connected yet: the trigger is `error` until it is.
 */
export class OnEvent {
  readonly connection: string | Connection;
  readonly event: string;
  readonly filters: JsonObject;
  readonly message: string | null;
  /** Keys conversations yourself: a template over the event as the app sent it, `"issue-{issue.number}"`. */
  readonly conversation: string | null;

  constructor(
    connection: string | Connection,
    event: string,
    options: { filters?: JsonObject; message?: string; conversation?: string } = {},
  ) {
    if (typeof connection !== "string" && !(connection instanceof Connection)) {
      throw new TypeError("OnEvent takes a Connection or its name");
    }
    this.connection = connection;
    this.event = event;
    this.filters = { ...(options.filters ?? {}) };
    this.message = options.message ?? null;
    this.conversation = options.conversation ?? null;
  }

  /** @internal A lazy `createIfMissing` connection is created first. */
  async toWire(): Promise<JsonObject> {
    let connection = this.connection;
    if (typeof connection !== "string") {
      const raw = await connection._ensure();
      connection = String(raw.origin === "app" ? raw.id : raw.name); // credential:<id> for one connected in the app
    }
    return {
      kind: "event", connection, event: this.event, filters: this.filters,
      ...compact({ message: this.message, conversation: this.conversation }),
    };
  }
}

/**
 * One of NoClick's own events (the types `Event.types()` lists, as your webhooks receive them): an
 * operation failing, a connection breaking, a channel halting, a workflow's run failing, an agent built
 * in the app asking for you, a payment going through. `type` names one, and `*` matches the
 * rest of a name (`"operation.*"`); `filters` are dotted paths into the event's `data` and the values
 * they must have. `message` is what the agent is told with every event, above it; `conversation`
 * keys conversations by a template over the event (`"connection-{data.id}"`), else each event is a
 * conversation of its own. The agent hears its user's events, and an agent of your account's hears
 * every event, your users' included. It never hears what its own turns caused, and a chain of
 * agents waking each other this way stops five turns deep. A channel subscribes to the same events
 * (`channel.subscribe(new OnPlatformEvent(...))`).
 *
 *     await ops.addTrigger(new OnPlatformEvent("workflow.run.failed", {
 *       conversation: "workflow-{data.workflow_id}", message: "A workflow failed. Find out why; pause it if it's useless.",
 *     }));
 */
export class OnPlatformEvent {
  readonly type: string;
  readonly filters: JsonObject | null;
  readonly message: string | null;
  readonly conversation: string | null;

  constructor(type: string, options: { filters?: JsonObject; message?: string; conversation?: string } = {}) {
    this.type = type;
    this.filters = options.filters ? { ...options.filters } : null;
    this.message = options.message ?? null;
    this.conversation = options.conversation ?? null;
  }

  /** @internal */
  toWire(): JsonObject {
    return {
      kind: "platform", type: this.type,
      ...compact({ filters: this.filters, message: this.message, conversation: this.conversation }),
    };
  }
}

/**
 * Each message on a queue becomes a turn: the agent reads `message` (its standing instructions,
 * if any) and then the message's JSON body. With `batchSize` above 1 (up to 25), one turn takes up
 * to that many waiting messages as a JSON list. `queue` is a `Queue` or its name, looked up for the
 * agent's own user. A turn that finishes acks its messages; one that fails hands them back (after
 * 30 seconds per attempt they've had), and a message that fails the queue's `maxAttempts` times
 * becomes a dead letter, the turn's error its `lastError`. Each turn is a conversation of its own,
 * unless `conversation` keys it from the message (one message a turn only). The agent takes one turn
 * at a time, in order; for more throughput raise `batchSize`, or put several agents on the queue.
 * While the agent is paused, messages wait.
 *
 * When the agent's budget, its user's cap or your account's funds run out, the trigger pauses
 * instead of failing turns: messages wait with their attempts unchanged, its `status` is `error`
 * saying why, and it carries on by itself once there's money to spend again.
 */
export class OnQueue {
  readonly queue: string | Queue;
  readonly message: string | null;
  readonly batchSize: number;
  readonly conversation: string | null;

  constructor(
    queue: string | Queue,
    options: { message?: string; batchSize?: number; conversation?: string } = {},
  ) {
    if (typeof queue !== "string" && !(queue instanceof Queue)) throw new TypeError("OnQueue takes a Queue or its name");
    const batchSize = options.batchSize ?? 1;
    if (!Number.isInteger(batchSize) || batchSize < 1) throw new RangeError(`batchSize is a whole number of messages, 1 or more, not ${batchSize}`);
    if (options.conversation !== undefined && batchSize !== 1) {
      throw new RangeError("conversation keys a turn by its one message; a batch holds several");
    }
    this.queue = queue;
    this.message = options.message ?? null;
    this.batchSize = batchSize;
    this.conversation = options.conversation ?? null;
  }

  /** @internal A lazy `createIfMissing` queue is created first. */
  async toWire(): Promise<JsonObject> {
    const queue = typeof this.queue === "string" ? this.queue : String((await this.queue._ensure()).name);
    return {
      kind: "queue", queue, batch_size: this.batchSize,
      ...compact({ message: this.message, conversation: this.conversation }),
    };
  }
}

/** What an agent's `triggers` take: a schedule, a webhook, an app event or a queue. */
export type TriggerDefinition = Cron | OnWebhook | OnEvent | OnPlatformEvent | OnQueue;

/** What `agent.updateTrigger` changes; `null` clears `message`, `conversation` or `filters`. */
export interface TriggerChanges {
  /** A schedule's new time, read in its `tz` (and its `message`, when it has one). */
  cron?: Cron;
  /** What the agent is told with every delivery. */
  message?: string | null;
  /** The template a webhook, event or queue trigger keys its conversations by. */
  conversation?: string | null;
  /** An app event's filters, by field, or a NoClick event's (dotted paths into its data): all of them, replacing its own. */
  filters?: JsonObject | null;
  /**
   * A channel trigger's: `mentions` (a person's post wakes the agents it names) or `all` (every person's post wakes
   * every agent in it). It's the channel's, so every agent in it hears it that way; your key needs `channels`.
   */
  mode?: "mentions" | "all";
}

export type AgentTriggerKind =
  "cron" | "webhook" | "event" | "platform" | "queue" | "email" | "call" | "approval" | "app" | "channel" | "routine";

/**
 * What makes a trigger that isn't live wake its agent again: `resume_agent` (`agent.resume()`), `resume`
 * (`agent.resumeTrigger`: it's paused, or its failures stopped it), `connect` (`connection`, by name, isn't connected),
 * `replace` (its connection was deleted: remove it and add one on another) or `open_in_app` (a step of its workflow).
 */
export interface TriggerFix {
  action: "resume_agent" | "resume" | "connect" | "replace" | "open_in_app";
  connection?: string;
}

/**
 * What an app event hears through, in words (`AgentTrigger.summary`): the app (`app`, `integration`, and `icon`, the
 * node type its mark is drawn by), the account as Connections names it (`account`; `number`, E.164, where it's a
 * phone's), which events it hears (`hears`; `groups` whether group chats reach it, where the app has groups), and
 * whether the account is linked (`status`: `connected`, `pending`, `disconnected` or `missing`), with `problem` and
 * `remedy` in words while it isn't.
 */
export interface TriggerSummary {
  app: string | null;
  integration: string | null;
  icon: string | null;
  credentialType: string | null;
  account: string | null;
  number: string | null;
  hears: string | null;
  groups: boolean | null;
  status: "connected" | "pending" | "disconnected" | "missing";
  problem: string | null;
  remedy: string | null;
}

/** Who set a trigger up: `person` (you, in the app, through the API or from your code), `agent` (that agent's own turn) or `automation` (a step of its workflow). */
export interface TriggerSetBy {
  kind: "person" | "agent" | "automation";
  agentId: string | null;
}

/** What a trigger takes through `agent.*Trigger`: `pause`, `resume`, `test`, `update` and `remove`. */
export type TriggerAction = "pause" | "resume" | "test" | "update" | "remove";

/** The kinds an agent's definition (`triggers=`) owns; `email` and `call` are set on the inbox or number. */
export const DEFINED_TRIGGER_KINDS: ReadonlySet<string> = new Set(["cron", "webhook", "event", "platform", "queue"]);

/**
 * One thing that wakes an agent, as `agent.triggers()` reads it. `kind` is `cron`, `webhook`, `event`,
 * `platform`, `queue`, `email`, `call`, `approval`, `app`, `channel` or `routine`. `spec` is its
 * definition (`name` for a webhook; `connection`, `event` and `filters` for an app event; `type` and
 * `filters` for a NoClick event; `message` and
 * `conversation` where they were given; `inbox_id` and `address` for email; `phone_number_id` and
 * `number` for calls; `cron`, `tz` and `message` for a schedule; `queue` and `batch_size` for a
 * queue; `tools`, the ones policy may hold, for an approval; `step`, `name`, `type` and
 * `operation` for a trigger wired into the agent in the app, as a step of its workflow, and changed only there;
 * `channel_id`, `name` and `mode` for a channel it sits in; `cron`, `tz`, `note` and `conversation` for a recurring
 * wake-up, changed through `agent.wakeups`).
 * An `approval` trigger is there while your policy may hold one of its
 * tools: an answered approval wakes it in the held call's conversation. `state` is `live`, `paused` (the agent,
 * or the trigger itself: `paused` says which) or `stopped` (it can't fire), `reason` says why in words and `fix`
 * what makes it live again. `status` is the older reading of it: `active`, `paused` or `error`, with `error` saying
 * why it can't fire (a connection that isn't connected, or its turns failing the same way five times in a row,
 * which stops it until it or the agent is resumed). `defined` is true for the kinds your code defines (`cron`,
 * `webhook`, `event`, `platform`, `queue`); `readOnly` for those changed where they live.
 */
export interface AgentTrigger {
  id: string;
  kind: AgentTriggerKind;
  spec: JsonObject;
  /** An app event's in a few words ("Messages to +1 202-555-0101"); null for other kinds. */
  title: string | null;
  /** What an app event hears through; null for other kinds. */
  summary: TriggerSummary | null;
  status: "active" | "paused" | "error";
  /** The URL a webhook trigger listens at (null for other kinds). */
  url: string | null;
  /** When a schedule next wakes the agent (null for other kinds, and while paused or in error). */
  nextRun: Date | null;
  /** When a schedule or a recurring wake-up comes round next, paused or not (null for other kinds). */
  nextRunAt: Date | null;
  lastFiredAt: Date | null;
  error: string | null;
  createdAt: Date | null;
  /** Paused on its own (`agent.pauseTrigger`), its agent running on. */
  paused: boolean;
  /** A turn it started is queued or running (for a channel, the agent's turn there). */
  running: boolean;
  state: "live" | "paused" | "stopped";
  reason: string | null;
  fix: TriggerFix | null;
  setBy: TriggerSetBy;
  readOnly: boolean;
  actions: TriggerAction[];
  defined: boolean;
  raw: JsonObject;
}

/** @internal A trigger as `triggers()` reads it, for agents and channels. */
export function toAgentTrigger(raw: JsonObject): AgentTrigger {
  const kind = String(raw.kind) as AgentTriggerKind;
  return {
    id: String(raw.id),
    kind,
    spec: raw.spec && typeof raw.spec === "object" ? { ...(raw.spec as JsonObject) } : {},
    title: str(raw.title),
    summary: toTriggerSummary(raw.summary),
    status: (str(raw.status) ?? "active") as AgentTrigger["status"],
    url: str(raw.url),
    nextRun: parseTime(raw.next_run),
    nextRunAt: parseTime(raw.next_run_at),
    lastFiredAt: parseTime(raw.last_fired_at),
    error: str(raw.error),
    createdAt: parseTime(raw.created_at),
    paused: raw.paused === true,
    running: raw.running === true,
    state: (str(raw.state) ?? "live") as AgentTrigger["state"],
    reason: str(raw.reason),
    fix: raw.fix && typeof raw.fix === "object" ? ({ ...(raw.fix as JsonObject) } as unknown as TriggerFix) : null,
    setBy: {
      kind: (str((raw.set_by as JsonObject | null)?.kind) ?? "person") as TriggerSetBy["kind"],
      agentId: str((raw.set_by as JsonObject | null)?.agent_id),
    },
    readOnly: raw.read_only === true,
    actions: Array.isArray(raw.actions) ? (raw.actions as TriggerAction[]) : [],
    defined: DEFINED_TRIGGER_KINDS.has(kind),
    raw,
  };
}

function toTriggerSummary(raw: unknown): TriggerSummary | null {
  if (!raw || typeof raw !== "object") return null;
  const s = raw as JsonObject;
  return {
    app: str(s.app),
    integration: str(s.integration),
    icon: str(s.icon),
    credentialType: str(s.credential_type),
    account: str(s.account),
    number: str(s.number),
    hears: str(s.hears),
    groups: typeof s.groups === "boolean" ? s.groups : null,
    status: (str(s.status) ?? "connected") as TriggerSummary["status"],
    problem: str(s.problem),
    remedy: str(s.remedy),
  };
}

/** @internal One definition's identity, to tell which triggers match your code. */
export function triggerKey(spec: JsonObject): string {
  const empty = (v: unknown) => v === null || v === undefined || (typeof v === "object" && !Array.isArray(v) && !Object.keys(v as JsonObject).length);
  return JSON.stringify(Object.keys(spec).filter((k) => !empty(spec[k])).sort().map((k) => [k, spec[k]]));
}

/**
 * @internal Which of an agent's triggers a definition names: a webhook by its name, unique on an agent; any other
 * by its whole definition (`triggerKey`).
 */
export function namedBy(spec: JsonObject): string {
  return triggerKey(spec.kind === "webhook" ? { kind: "webhook", name: spec.name } : spec);
}
