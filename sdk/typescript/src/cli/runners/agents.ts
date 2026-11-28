/**
 * Agents and users, as the Python CLI's `agents list`, `agents chat`, `users list` and `users create` are: the same
 * flags, lines, `--json` and exit codes.
 */

import { Agent } from "../../agent.ts";
import { NotFound } from "../../errors.ts";
import { ALL_USERS } from "../../scope.ts";
import { User } from "../../user.ts";
import type { Values } from "../args.ts";
import { INTERRUPTED, OK } from "../exits.ts";
import { host } from "../host.ts";
import { type Io, printJson } from "../output.ts";
import { num, on, str, table } from "./kit.ts";

export async function agentsList(values: Values, io: Io): Promise<number> {
  const limit = num(values, "limit") ?? 50;
  // One more than shown says whether there are more.
  let agents = await Agent.list({ limit: limit ? limit + 1 : undefined, userFilter: on(values, "all_users") ? ALL_USERS : undefined, user: str(values, "user") });
  const more = Boolean(limit) && agents.length > limit;
  if (limit) agents = agents.slice(0, limit);
  if (on(values, "json")) {
    printJson(io, agents);
    return OK;
  }
  table(io, ["NAME", "MODEL", "USER", "CREATED", "ID"],
    agents.map((a) => [a.name, a.model, a.userId ?? "account", a.createdAt, a.id]), "No agents yet.", "Agents");
  if (more) io.err(`The first ${limit}: there are more (--limit 0 lists every one).`);
  return OK;
}

/** The agent `name` the scope can talk to: with `--user`, that user's own, else the account's. An expired one takes
 *  no turns. */
export async function agentToTalkTo(name: string, user: string | undefined): Promise<Agent> {
  const live = (await Agent.list({ name, user })).filter((a) => a.status !== "expired");
  const agent = live.sort((a, b) => Number(a.userId === null) - Number(b.userId === null))[0];
  if (!agent) throw new NotFound(`No agent is named '${name}'.`, { nextStep: "List agents with: noclick agents list" });
  return agent;
}

const INTERRUPTED_ = Symbol("interrupted");

/** `work`, or `INTERRUPTED_` once Ctrl-C is pressed while it runs (which then stops waiting, not the work). */
export async function untilInterrupted<T>(work: Promise<T>): Promise<T | typeof INTERRUPTED_> {
  let stop: () => void = () => {};
  const stopped = new Promise<typeof INTERRUPTED_>((done) => {
    stop = () => done(INTERRUPTED_);
    process.once("SIGINT", stop);
  });
  try {
    return await Promise.race([work, stopped]);
  } finally {
    process.off("SIGINT", stop);
  }
}

/** One turn a line: what's typed at a terminal (Ctrl-D or /exit leaves) or each line piped in; `-m` one message. */
export async function agentsChat(values: Values, io: Io): Promise<number> {
  const name = String(values.name);
  const user = str(values, "user");
  const agent = await agentToTalkTo(name, user);
  let conversation = str(values, "conversation");
  const message = str(values, "message");
  const interactive = message === undefined && host.stdinIsTty();
  if (interactive) io.err(`Talking to ${name}. Ctrl-D or /exit to leave.`);
  const said = message !== undefined ? [message] : host.lines(() => "you> ");
  for await (const text of said) {
    if (["/exit", "/quit"].includes(text.trim())) break;
    if (!text.trim()) continue;
    const turn = await agent.send(text, { conversation, user });
    const reply = await untilInterrupted(turn.wait());
    if (reply === INTERRUPTED_) {
      io.err(`\nThe turn keeps running. Read its reply with: noclick ops wait ${turn.id}`);
      return INTERRUPTED;
    }
    conversation = reply.conversation ?? conversation;
    const tools = reply.toolCalls.map((call) => String(call.tool));
    if (tools.length) io.err(`(${tools.join(", ")})`);
    io.out(reply.text);
    if (interactive) io.out("");
  }
  if (conversation) io.err(`Conversation ${conversation}: continue it with --conversation ${conversation}`);
  return OK;
}

export async function usersList(values: Values, io: Io): Promise<number> {
  const users = await User.list({
    q: str(values, "q"), status: str(values, "status") as "active" | "suspended" | undefined, limit: num(values, "limit"),
  });
  if (on(values, "json")) {
    printJson(io, users);
    return OK;
  }
  table(io, ["ID", "NAME", "EMAIL", "STATUS", "CREATED"], users.map((u) => [u.id, u.name, u.email, u.status, u.createdAt]),
    "No users yet.", "Users");
  return OK;
}

export async function usersCreate(values: Values, io: Io): Promise<number> {
  const user = await User.create(String(values.id), {
    name: str(values, "name"), email: str(values, "email"), phone: str(values, "phone"), spendCapUsdPerMonth: num(values, "spend_cap"),
  });
  if (on(values, "json")) printJson(io, user);
  else {
    io.out(user.id);
    io.err(`Created user ${user.id}.`);
  }
  return OK;
}
