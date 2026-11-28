/**
 * `noclick live`: the app's live session as an agent's development loop, as the Python CLI's `noclick/_cli/parts/
 * live.py` is. The site runs on a dev server with the app's real bindings, at the app's own URL; what's pushed to
 * `noclick-live` (`noclick live push`) shows at once, and `noclick live end` builds, checks and deploys it.
 */

import { NotAvailable } from "../../errors.ts";
import type { LiveSession } from "../../live.ts";
import { Deployment, Project } from "../../project.ts";
import type { Values } from "../args.ts";
import { OK } from "../exits.ts";
import { host } from "../host.ts";
import * as links from "../link.ts";
import { type Io, printJson } from "../output.ts";
import { check } from "../spend.ts";
import { CommandError } from "../store.ts";
import { num, on, str } from "./kit.ts";
import { git, push } from "./ship.ts";

export const LIVE_BRANCH = "noclick-live";
const POLL_MS = 2000;

function appOf(values: Values): Project {
  return Project.fromName(links.appName(str(values, "project") ?? null, host.cwd()));
}

function printSession(io: Io, session: LiveSession): void {
  io.err(`Session ${session.id}: ${session.state}${session.phase ? ` (${session.phase})` : ""}`);
  const edits = session.edits;
  if (edits.count) io.err(`  edits: ${edits.count} (${edits.hot} in place, ${edits.reload} reloaded, ${edits.error} failed)`);
  if (session.git) {
    io.err(`  branch ${session.git.branch} at ${String(session.git.head ?? "").slice(0, 7)}${session.git.conflict ? ", conflict" : ""}`);
  }
  if (session.error) io.err(`  error: ${session.error.message}`);
}

export async function liveStart(values: Values, io: Io): Promise<number> {
  const app = appOf(values);
  const hours = num(values, "hours") ?? 1;
  const timeout = num(values, "timeout") ?? 300;
  await check(io, [{ kind: "live_editing", usage: { hours } }], num(values, "max_usd"), { what: `A session of up to ${hours} hours`, per: "at most" });
  const status = await app.live.status();
  if (!status.supported) {
    throw new NotAvailable(`${app.name} can't be edited live: ${status.unsupportedReason}`, { nextStep: "Deploy it with noclick deploy instead." });
  }
  if (!status.enabled) {
    await app.update({ liveEditing: true });
    io.err(`Turned live editing on for ${app.name}.`);
  }
  let session = await app.live.start({ wait: true, limits: { maxSessionS: Math.trunc(hours * 3600) } });
  const enter = session.enterUrl;
  const ends = Date.now() + timeout * 1000;
  while (session.state === "warming" && Date.now() < ends) {
    await host.sleep(POLL_MS);
    session = (await app.live.status()).session ?? session;
  }
  if (on(values, "json")) {
    printJson(io, session.raw);
    return OK;
  }
  printSession(io, session);
  if (session.state === "warming") {
    io.err(`Still starting after ${timeout}s: the link below shows it once it's live (noclick live status reads it again).`);
  }
  io.err(`The app's URL, ${session.url}, shows production to everyone but whoever opens the link below.`);
  io.err("Push edits with: noclick live push (they show at once). Ship them with: noclick live end");
  const last = enter ?? session.url;
  if (last) io.out(last);
  return OK;
}

export async function liveStatus(values: Values, io: Io): Promise<number> {
  const status = await appOf(values).live.status();
  if (on(values, "json")) {
    printJson(io, status.raw);
    return OK;
  }
  if (!status.supported) {
    io.err(`Can't be edited live: ${status.unsupportedReason}`);
    return OK;
  }
  if (status.session === null) {
    io.err("No session yet: start one with noclick live");
    return OK;
  }
  printSession(io, status.session);
  if (status.session.open && status.session.url) io.out(status.session.url);
  return OK;
}

export async function livePush(values: Values, io: Io): Promise<number> {
  const app = await appOf(values).hydrate();
  const root = await git(["rev-parse", "--show-toplevel"], host.cwd());
  if (await git(["status", "--porcelain", "--untracked-files=no"], root)) {
    throw new CommandError("Your checkout has uncommitted changes.", { nextStep: "Commit them: live push sends the commit you're on." });
  }
  const sha = await git(["rev-parse", "HEAD"], root);
  if (!app.repo) throw new CommandError(`${app.name} has no repo to push to.`, { nextStep: "Deploy it with noclick deploy instead." });
  await push(root, app.repo, sha, LIVE_BRANCH);
  io.err(`Pushed ${sha.slice(0, 7)} to ${LIVE_BRANCH}: it shows in the session's pages now.`);
  return OK;
}

const SAID: Record<string, string> = {
  deployed: "Deployed: production serves what was edited.", no_changes: "Nothing was edited.",
  stopped: "Stopped without deploying.", aborted: "An edit came in as it ended: it's live again.",
};

export async function liveEnd(values: Values, io: Io): Promise<number> {
  const app = appOf(values);
  const deploy = !on(values, "no_deploy");
  const op = await app.live.end({ deploy });
  if (on(values, "no_wait")) {
    io.out(op.id);
    io.err(`Ending. Wait for it with: noclick wait ${op.id}`);
    return OK;
  }
  io.err(deploy ? "Building, checking and deploying what was edited…" : "Stopping…");
  const ended = await op.wait({ timeoutS: num(values, "timeout") });
  if (on(values, "json")) {
    printJson(io, ended.raw);
    return OK;
  }
  io.err(SAID[ended.outcome] ?? ended.outcome);
  if (ended.mainBehind) io.err("Production's branch couldn't move to it yet: the next session's start merges it.");
  if (ended.deploymentId) {
    const url = (await Deployment.fromId(ended.deploymentId).hydrate()).url;
    if (url) io.out(String(url));
  }
  return OK;
}

