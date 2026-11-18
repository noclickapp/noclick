/**
 * What runs on NoClick for you now: your machines (with the conversations on each), every agent's sandbox that's up,
 * and your live sandboxes, each with its price an hour.
 *
 *     const running = await compute({ userFilter: "all" });
 *     const perHour = running.filter((c) => c.status === "running").reduce((sum, c) => sum + (c.usdPerHour ?? 0), 0);
 */

import { resolveClient } from "./client.ts";
import { asList, asObject, num, parseTime, readScope, str } from "./object.ts";
import type { JsonObject, ReadOptions } from "./object.ts";

/** A conversation running on a machine or in an agent's sandbox. */
export interface ComputeRun {
  agentId: string | null;
  agentName: string | null;
  /** The agent's conversation (as `agent.message({ conversation })` names it). */
  conversation: string | null;
  harness: string | null;
  /** `starting`, `live` or `running`. */
  state: string;
}

/** A machine, an agent's sandbox or a sandbox, as it runs now. */
export interface ComputeItem {
  /** `machine` (a NoClick machine, any status), `agent_sandbox` (an agent's warm sandbox) or `sandbox` (`Sandbox`). */
  kind: "machine" | "agent_sandbox" | "sandbox";
  /** Its id (an agent's sandbox: its name). */
  id: string;
  /** The machine's name, the agent's, or a sandbox's image. */
  name: string | null;
  status: string | null;
  userId: string | null;
  region: string | null;
  cpu: number | null;
  memoryGb: number | null;
  startedAt: Date | null;
  /** What an hour of it costs (a machine: its month's price over 730 hours). */
  usdPerHour: number | null;
  /** A machine's price a month. */
  usdPerMonth: number | null;
  /** What an agent's sandbox charged since midnight UTC. */
  spentUsdToday: number | null;
  running: ComputeRun[];
  raw: JsonObject;
}

function toItem(raw: JsonObject): ComputeItem {
  return {
    kind: str(raw.kind) as ComputeItem["kind"], id: str(raw.id) ?? "", name: str(raw.name), status: str(raw.status),
    userId: str(raw.user_id), region: str(raw.region), cpu: num(raw.cpu), memoryGb: num(raw.memory_gb),
    startedAt: parseTime(raw.started_at), usdPerHour: num(raw.usd_per_hour), usdPerMonth: num(raw.usd_per_month),
    spentUsdToday: num(raw.spent_usd_today),
    running: (Array.isArray(raw.running) ? raw.running : []).map(asObject).map((r) => ({
      agentId: str(r.agent_id), agentName: str(r.agent_name), conversation: str(r.conversation),
      harness: str(r.harness), state: str(r.state) ?? "",
    })),
    raw,
  };
}

/**
 * Your machines (any status, with the conversations on each), every agent's sandbox up now and every live `Sandbox`,
 * each with its price an hour. Each part needs its area's scope (`machines`, `agents`, `sandboxes`); a key with only
 * some gets those. Your own computers aren't in it.
 */
export async function compute(options: ReadOptions = {}): Promise<ComputeItem[]> {
  const { user, userId } = await readScope(options);
  const page = await resolveClient(options.client).request("GET", "/v1/compute", { query: { user_id: userId }, user });
  return asList(page).map((row) => toItem(asObject(row)));
}
