/**
 * Reaching a machine and receiving events, as the Python CLI's `machines ssh` and `webhooks listen` are.
 */

import { createHmac, randomBytes } from "node:crypto";

import { Machine } from "../../machine.ts";
import { ALL_USERS } from "../../scope.ts";
import { Event, WEBHOOK_SIGNATURE_HEADER } from "../../webhook.ts";
import { VERSION } from "../../version.ts";
import type { Values } from "../args.ts";
import { OK } from "../exits.ts";
import { host } from "../host.ts";
import type { Io } from "../output.ts";
import { CommandError } from "../store.ts";
import { attachShell } from "../terminal.ts";
import { str } from "./kit.ts";

const POLL_MS = 2000;
const USER_AGENT = `noclick-cli/${VERSION}`;

/** Your terminal on a machine's shell, raw, until its bash ends; exits with bash's exit code. It renews, so the shell
 *  lasts 15 minutes at a time and goes on. A terminal is asked for before any shell is opened for it. */
export async function machinesSsh(values: Values, _io: Io): Promise<number> {
  if (process.platform === "win32" || !host.stdinIsTty() || !process.stdout.isTTY) {
    throw new CommandError("noclick machines ssh needs a terminal on macOS or Linux (on Windows, use WSL).");
  }
  const machine = Machine.fromName(String(values.name));
  const opened = await machine.shell();
  return await attachShell(opened.url, opened.token, async () => (await machine.shell()).token, "noclick machines ssh");
}

/** The `NoClick-Signature` header a delivery carries: HMAC-SHA256 over `timestamp.body`. */
export function sign(secret: string, body: string, timestamp: number): string {
  return `t=${timestamp},v1=${createHmac("sha256", secret).update(`${timestamp}.${body}`).digest("hex")}`;
}

async function forward(url: string, secret: string, event: Event): Promise<string> {
  const body = JSON.stringify(event.raw);
  try {
    const response = await fetch(url, {
      method: "POST", body,
      headers: { "Content-Type": "application/json", "User-Agent": USER_AGENT, [WEBHOOK_SIGNATURE_HEADER]: sign(secret, body, Math.floor(Date.now() / 1000)) },
    });
    return `${response.status} ${response.statusText}`.trimEnd();
  } catch (err) {
    return `failed: ${(err as Error).name}`;
  }
}

const clock = (at: Date | null) => (at ?? new Date()).toTimeString().slice(0, 8);

/** Every event (or `--events`' types), signed as a real delivery is, POSTed to a local URL until Ctrl-C. */
export async function webhooksListen(values: Values, io: Io): Promise<number> {
  const secret = str(values, "secret") ?? `nk_whsec_${randomBytes(24).toString("hex")}`;
  const types = (str(values, "events") ?? "").split(",").filter(Boolean);
  const to = String(values.forward_to);
  io.err(`Forwarding ${types.length ? types.join(", ") : "every event"} to ${to}. Ctrl-C stops.`);
  io.err(`Signing secret for this session: ${secret}  (check it with noclick.Webhook.verify)`);
  // Like a webhook with no user: your account's events and every user's, unless --user narrows it.
  const users = str(values, "events_user") ?? ALL_USERS;
  let since = new Date();
  let seen = new Set<string>();
  let stopped = false;
  const caught = host.interrupted();
  void caught.promise.then(() => { stopped = true; });
  try {
    while (!stopped) {
      const events = await Event.list({ type: types.length ? types : undefined, since, userFilter: users });
      events.sort((a, b) => (a.createdAt?.getTime() ?? 0) - (b.createdAt?.getTime() ?? 0));
      for (const event of events) {
        if (seen.has(event.id)) continue;
        const outcome = await forward(to, secret, event);
        io.out(`${clock(event.createdAt)}  ${String(event.type).padEnd(28)} ${event.id}  -> ${outcome}`);
      }
      if (events.length) { // `since` is inclusive: remember only what sits on the boundary
        since = events.at(-1)!.createdAt ?? since;
        seen = new Set(events.filter((e) => e.createdAt?.getTime() === since.getTime()).map((e) => e.id));
      }
      if (!stopped) await host.sleep(POLL_MS);
    }
  } finally {
    caught.release();
  }
  return OK;
}
