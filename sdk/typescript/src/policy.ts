/**
 * Policy: which tools may run, for the account or one user.
 *
 * Patterns match tool names in dotted form (`gmail.*`,
 * `slack.send_message_to_channel`, `*.delete_*`, `search`). A user policy
 * narrows the account policy; deny wins; an empty `allow` allows everything.
 * A `requireApproval` match makes the call throw `ApprovalRequired` until a
 * person approves it; retry with `{ approvalId }`. Like every call, `get`, `set`
 * and `evaluate` follow `asUser`: inside it they address that user's policy, and
 * `{ user: null }` addresses the account's. A rule can also be a `Rule` with a condition on the
 * call's arguments and a person who approves it.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { Human } from "./human.ts";
import { asObject, compact, paginate, str } from "./object.ts";
import type { JsonObject } from "./object.ts";
import { resolveScope, userIdOf } from "./scope.ts";
import type { UserOption } from "./scope.ts";

type ListName = "allow" | "deny" | "require_approval";

/** A rule as your code gives it: a pattern, a `Rule`, or an object with a rule's fields. */
export type RuleInput = string | Rule | { tool: string; when?: string | null; approver?: Human | string | null; message?: string | null };

/**
 * A policy rule that says more than a pattern: `tool` is the pattern, `when` a CEL expression the
 * call must satisfy for the rule to apply, over `args` (the call's final arguments, bound ones
 * included) and `user` (`id`, `email`, `name`, `metadata`), and `approver` who approves it in
 * `requireApproval`: a `Human` (`new Human()` for the user the call is made for) or an email; it's
 * emailed the approval, and only it may answer. Without an `approver` the owner of what the call
 * acts in approves, as for a pattern. A call `when` can't judge (an argument it lacks, values that
 * don't compare) meets a `deny` or `requireApproval` rule and misses an `allow` one; numbers
 * compare within their own type (`double(args.amount) > 99.5` for an amount with a fraction).
 * `message`, on a `deny` rule, is what the call's refusal says in your words, so the agent can tell
 * the user what to do ("Web search comes with Pro: https://..."); `{{user.*}}` in it is filled in for
 * whom the call is for.
 *
 *     await Policy.add([new Rule("stripe.create_refund", { when: "args.amount > 10000", approver: "finance@acme.com" })]);
 */
export class Rule {
  readonly tool: string;
  readonly when: string | null;
  readonly approver: Human | string | null;
  /** What a `deny` rule's refusal says, for the user. */
  readonly message: string | null;

  constructor(tool: string, options: { when?: string | null; approver?: Human | string | null; message?: string | null } = {}) {
    this.tool = tool;
    this.when = options.when ?? null;
    this.approver = options.approver ?? null;
    this.message = options.message ?? null;
  }

  /** @internal */
  static _parse(entry: RuleInput): string | Rule {
    if (typeof entry === "string" || entry instanceof Rule) return entry;
    if (entry && typeof entry === "object" && typeof entry.tool === "string") {
      const unknown = Object.keys(entry).filter((k) => !["tool", "when", "approver", "message"].includes(k));
      if (!unknown.length) return new Rule(entry.tool, { when: entry.when, approver: entry.approver, message: entry.message });
    }
    throw new TypeError(`A policy rule is a pattern, a Rule or { tool, when?, approver?, message? }, not ${JSON.stringify(entry)}`);
  }

  /** @internal A list entry as the API returns it. */
  static _read(raw: unknown): string | Rule {
    if (!raw || typeof raw !== "object") return String(raw);
    const row = raw as JsonObject;
    const approver = asObject(row.approver);
    const who = str(approver.user_id) ? new Human({ user: String(approver.user_id) }) : approver.user ? new Human() : str(approver.email);
    return new Rule(String(row.tool), { when: str(row.when), approver: who, message: str(row.message) });
  }

  /** @internal */
  async _wire(list: ListName): Promise<string | JsonObject> {
    if (this.approver !== null && list !== "require_approval") throw new TypeError(`Only a requireApproval rule has an approver, not one in ${list}`);
    if (this.message !== null && list !== "deny") throw new TypeError(`Only a deny rule has a message, not one in ${list}`);
    if (this.when === null && this.approver === null && this.message === null) return this.tool;
    let approver: JsonObject | undefined;
    if (typeof this.approver === "string") approver = { email: this.approver };
    else if (this.approver instanceof Human) {
      const { phone, ...address } = await this.approver._toolAddress();
      if (phone !== undefined && !("email" in address)) throw new TypeError("An approver answers by email or on the approval page; give the Human an email");
      approver = address;
    }
    return compact({ tool: this.tool, when: this.when ?? undefined, approver, message: this.message ?? undefined });
  }
}

export interface PolicyRules {
  allow?: RuleInput[];
  deny?: RuleInput[];
  requireApproval?: RuleInput[];
}

/** Rules not saved yet, judged in place of one layer's saved rules. */
export interface PolicyDraft extends PolicyRules {
  layer: "account" | "user";
}

/** What a policy decides for one tool, and which rule decided it. */
export interface PolicyVerdict {
  /** The tool's dotted name. */
  tool: string;
  verdict: "allow" | "deny" | "approval";
  matchedPattern: string | null;
  /** `account` or `user` (null when nothing matched). */
  layer: string | null;
  /** The rule that decided, whole: a pattern or a `Rule` (null when nothing matched). */
  rule: string | Rule | null;
  raw: JsonObject;
}

async function wireRules(list: ListName, rules: readonly RuleInput[] | undefined): Promise<(string | JsonObject)[]> {
  if (rules !== undefined && !Array.isArray(rules)) throw new TypeError(`${list} takes a list of patterns and rules`);
  return await Promise.all((rules ?? []).map((entry) => {
    const rule = Rule._parse(entry);
    return typeof rule === "string" ? rule : rule._wire(list);
  }));
}

export interface PolicyOptions {
  /** The user whose policy this is (a `User` or your id for one); omitted = the `asUser` user, else the account's; null = the account's. */
  user?: UserOption;
  client?: NoClick;
}

function rules(value: unknown): (string | Rule)[] {
  return Array.isArray(value) ? value.map(Rule._read) : [];
}

export class Policy {
  /** Whose policy this is (your id for the user; null for the account's). */
  readonly userId: string | null;
  /** Patterns, and `Rule`s where a rule has a condition or an approver. */
  readonly allow: (string | Rule)[];
  readonly deny: (string | Rule)[];
  readonly requireApproval: (string | Rule)[];
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    this.userId = str(raw.user_id);
    this.allow = rules(raw.allow);
    this.deny = rules(raw.deny);
    this.requireApproval = rules(raw.require_approval);
    this.raw = raw;
  }

  /** The account's policy, or with `{ user }` that user's own rules. */
  static async get(options: PolicyOptions = {}): Promise<Policy> {
    const userId = await userIdOf(resolveScope(options.user));
    const raw = await resolveClient(options.client).request("GET", "/v1/policy", {
      query: { user_id: userId },
      user: null,
    });
    return new Policy(asObject(raw));
  }

  /** The account's policy and every user policy. */
  static async list(options: { client?: NoClick } = {}): Promise<Policy[]> {
    return (await paginate(resolveClient(options.client), "/v1/policies", { user: null })).map((raw) => new Policy(raw));
  }

  /**
   * How the policy judges each of `tools` (dotted or wire names, at most 500) for the account,
   * or `{ user }`. A `draft` is judged in place of its layer's saved rules. Nothing runs and
   * no approval is requested. `arguments` judges one tool's call with those
   * arguments, so rules with a `when` apply; without them a rule with a `when` never matches.
   */
  static async evaluate(
    tools: string | readonly string[],
    options: PolicyOptions & { draft?: PolicyDraft; arguments?: JsonObject } = {},
  ): Promise<PolicyVerdict[]> {
    const userId = await userIdOf(resolveScope(options.user));
    const names = typeof tools === "string" ? [tools] : [...tools];
    if (options.arguments !== undefined && names.length !== 1) throw new TypeError("arguments judges one call: pass one tool with it");
    const draft = options.draft && {
      layer: options.draft.layer,
      allow: await wireRules("allow", options.draft.allow),
      deny: await wireRules("deny", options.draft.deny),
      require_approval: await wireRules("require_approval", options.draft.requireApproval),
    };
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/policy/evaluate", {
      json: compact({ tools: names, arguments: options.arguments, user_id: userId, draft }),
      user: null,
    }));
    return (Array.isArray(raw.results) ? (raw.results as JsonObject[]) : []).map((row) => ({
      tool: String(row.tool),
      verdict: row.verdict as PolicyVerdict["verdict"],
      matchedPattern: str(row.matched_pattern),
      layer: str(row.layer),
      rule: row.rule === undefined || row.rule === null ? null : Rule._read(row.rule),
      raw: row,
    }));
  }

  /** Replace the policy: lists left out are sent empty. */
  static async set(rules: PolicyRules, options: PolicyOptions = {}): Promise<Policy> {
    const userId = await userIdOf(resolveScope(options.user));
    const raw = await resolveClient(options.client).request("PUT", "/v1/policy", {
      json: compact({
        user_id: userId,
        allow: await wireRules("allow", rules.allow),
        deny: await wireRules("deny", rules.deny),
        require_approval: await wireRules("require_approval", rules.requireApproval),
      }),
      user: null,
    });
    return new Policy(asObject(raw));
  }

  /**
   * Add rules to one list (`to`: `requireApproval` by default, `deny` or `allow`) of the account's
   * policy (or `{ user }`'s), leaving every other rule as it is, in one change on the server. A rule
   * for a tool that list already has replaces it, so code that owns a rule can add it on every run.
   *
   *     await Policy.add(["quickbooks.create_bill"]);
   *     await Policy.add(["slack.*"], { to: "deny", user: "user_42" });
   */
  static async add(rules: readonly RuleInput[], options: PolicyOptions & { to?: "requireApproval" | "deny" | "allow" } = {}): Promise<Policy> {
    if (!rules.length) throw new TypeError("Policy.add() takes at least one rule");
    const list: ListName = options.to === "requireApproval" || options.to === undefined ? "require_approval" : options.to;
    const userId = await userIdOf(resolveScope(options.user));
    const raw = await resolveClient(options.client).request("POST", "/v1/policy/add", {
      json: compact({ list, rules: await wireRules(list, rules), user_id: userId }),
      user: null,
    });
    return new Policy(asObject(raw));
  }

  /**
   * Remove the rules for these tools, as written, from every list of the account's policy (or
   * `{ user }`'s), leaving the rest. A tool with no rule changes nothing.
   */
  static async remove(tools: readonly string[], options: PolicyOptions = {}): Promise<Policy> {
    if (!tools.length) throw new TypeError("Policy.remove() takes the tool patterns whose rules go");
    const userId = await userIdOf(resolveScope(options.user));
    const raw = await resolveClient(options.client).request("POST", "/v1/policy/remove", {
      json: compact({ tools: [...tools], user_id: userId }),
      user: null,
    });
    return new Policy(asObject(raw));
  }
}
