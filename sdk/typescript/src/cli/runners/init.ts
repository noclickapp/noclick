/**
 * `noclick init`: a folder becomes an app, from a template or drafted by the app's coding agent from what you
 * describe, and is linked; as the Python CLI's `noclick/_cli/parts/start.py` is. The templates are the manifest's.
 */

import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";

import { defaultClient } from "../../client.ts";
import { NotFound } from "../../errors.ts";
import { Project } from "../../project.ts";
import { Repo } from "../../repo.ts";
import type { Values } from "../args.ts";
import { OK } from "../exits.ts";
import { host } from "../host.ts";
import * as links from "../link.ts";
import { type Io, withRun } from "../output.ts";
import { load } from "../spec.ts";
import { CommandError } from "../store.ts";
import { num, on, str } from "./kit.ts";
import { git, remote } from "./ship.ts";

// The branch the app's coding agent pushes its work to, outside a live session.
const CODER_BRANCH = "noclick-code";
const DRAFT_TIMEOUT_S = 900;

function templates(): Record<string, { about: string; files: Record<string, string> }> {
  return load().manifest.templates;
}

/** `template`'s files for an app called `name`. */
function filesOf(template: string, name: string): Record<string, string> {
  return Object.fromEntries(Object.entries(templates()[template]!.files).map(([path, text]) =>
    [path, text.split("{name}").join(name).split("{{").join("{").split("}}").join("}")]));
}

function appNameOf(values: Values, folder: string): string {
  const name = str(values, "name") ?? basename(resolve(folder)).toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "");
  if (!name) {
    throw withRun(new CommandError("Name the app: this folder's name makes none.", { nextStep: "noclick init <name>" }),
      ["noclick init <name> --template <template>"]);
  }
  return name;
}

function writeFiles(folder: string, files: Record<string, string>): void {
  const taken = Object.keys(files).filter((path) => existsSync(join(folder, path))).sort();
  if (taken.length) {
    throw new CommandError(`The folder already has ${taken.join(", ")}: init writes only new files.`,
      { nextStep: "Run it in an empty folder, or pass --dir <new folder>." });
  }
  for (const [path, text] of Object.entries(files)) {
    mkdirSync(dirname(join(folder, path)), { recursive: true });
    writeFileSync(join(folder, path), text);
  }
}

async function gitInit(folder: string): Promise<void> {
  if (!existsSync(join(folder, ".git"))) await git(["init", "--quiet", "--initial-branch", "main"], folder);
}

/** Check the coding agent's branch out in `folder` as main, through a remote that never lands in its git config or
 *  the process list; its head's sha. */
async function fetchDraft(folder: string, repo: Repo, branch: string): Promise<string> {
  await gitInit(folder);
  const env = remote(await repo.cloneUrl({ write: false, ttlS: 600 }));
  await git(["fetch", "--quiet", "noclick-deploy", `refs/heads/${branch}`], folder, env);
  await git(["checkout", "--quiet", "-B", "main", "FETCH_HEAD"], folder);
  return await git(["rev-parse", "HEAD"], folder);
}

export async function init(values: Values, io: Io): Promise<number> {
  const folder = resolve(host.cwd(), str(values, "dir") ?? ".");
  const template = str(values, "template");
  const describe = str(values, "describe");
  const names = Object.keys(templates());
  if (on(values, "fetch")) {
    const name = links.appName(str(values, "name") ?? null, folder);
    const app = await Project.fromName(name).hydrate();
    if (!app.repo) throw new NotFound(`${name} has no repo to check out.`);
    const sha = await fetchDraft(folder, app.repo, CODER_BRANCH);
    io.err(`Checked the coding agent's draft of ${name} out here (${sha.slice(0, 7)}). Next: noclick deploy`);
    io.out(name);
    return OK;
  }
  if (Boolean(template) === Boolean(describe)) {
    throw new CommandError('Say what to start from: --template <name> or --describe "what you want".',
      { nextStep: `Templates: ${names.join(", ")}. Or: noclick init --describe "a page that takes bookings"` });
  }
  mkdirSync(folder, { recursive: true });
  const name = appNameOf(values, folder);
  if (template) {
    if (!names.includes(template)) throw new CommandError(`There's no template '${template}'.`, { nextStep: `Pick one of: ${names.join(", ")}` });
    writeFiles(folder, filesOf(template, name));
  } else if (readdirSync(folder).some((entry) => entry !== ".git" && entry !== links.FOLDER)) {
    throw new CommandError("--describe drafts the app into an empty folder, and this one has files.",
      { nextStep: "Run it in a new folder (--dir <new folder>), or start from your files with noclick deploy --create." });
  }
  const repo = Repo.fromName(name, { createIfMissing: true });
  const app = await Project.fromName(name, { repo, createIfMissing: true }).hydrate();
  links.write(name, { appId: app.id, apiUrl: defaultClient().baseUrl, root: folder });
  io.err(`Linked ${folder} to the app ${name} (.noclick/project.json).`);
  if (template) {
    await gitInit(folder);
    io.err(`Wrote the ${template} template: ${templates()[template]!.about}`);
    io.err("Next: noclick deploy");
    io.out(name);
    return OK;
  }
  io.err("Handing what you described to the app's coding agent: it writes the app and pushes it (its work is charged to your account, at what its model costs).");
  const job = await app.live.change(describe!, { title: `Draft ${name}` });
  if (on(values, "no_wait")) {
    io.out(job.id);
    io.err(`Drafting. Wait for it with: noclick wait ${job.id}, then check it out here: noclick init --fetch`);
    return OK;
  }
  const reply = await job.wait({ timeoutS: num(values, "timeout") ?? DRAFT_TIMEOUT_S });
  io.err(reply.text);
  const code = (reply as { raw?: Record<string, unknown> }).raw?.code;
  const branch = (code && typeof code === "object" ? (code as { branch?: string }).branch : undefined) || CODER_BRANCH;
  let sha: string;
  try {
    sha = await fetchDraft(folder, (await Repo.fromName(name).hydrate()), branch);
  } catch (err) {
    if (!(err instanceof CommandError)) throw err;
    throw new NotFound(`The coding agent pushed nothing to ${branch}: ${err.message}`,
      { nextStep: `Read what it said above, then ask again: noclick init --describe "..." --dir ${str(values, "dir") ?? "."}` });
  }
  io.err(`Checked its draft out here (${sha.slice(0, 7)}). Next: noclick deploy`);
  io.out(name);
  return OK;
}
