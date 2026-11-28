/**
 * Shipping an app from any folder, and reading and moving its releases, as the Python CLI's `deploy`, `link`,
 * `status`, `open`, `releases`, `rollback`, `promote` and `delete` do.
 *
 * A clean git checkout pushes the commit it's on. Anything else (no git, `--no-git`, or a checkout with uncommitted or
 * untracked files) ships the folder as a commit of its own through the API: in a checkout the files git would track,
 * outside one every file but the default excludes and what its `.gitignore` names. A file that looks like a secret
 * (`.env`, a key, a login) is left out, never shipped, and the deploy says how to give the app its values with
 * `noclick secret set`; only one committed in the commit a deploy ships refuses it.
 */

import { execFile } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, relative, resolve, sep } from "node:path";

import { Conflict, NotFound, OperationFailed } from "../../errors.ts";
import type { Operation } from "../../operation.ts";
import { Deployment, Project } from "../../project.ts";
import { Repo } from "../../repo.ts";
import { UsageError, type Values } from "../args.ts";
import { host } from "../host.ts";
import { FAILED, OK, USAGE } from "../exits.ts";
import * as links from "../link.ts";
import { OUT } from "../style.ts";
import { type Io, printJson } from "../output.ts";
import { CommandError, resolveCredentials } from "../store.ts";
import { ID, answer, appOf, cell, lookup, noteUnclaimed, num, on, profileOf, str, table, usd } from "./kit.ts";

/** Git never waits on a prompt, nor on a server that sends nothing for this long. */
const GIT_GIVE_UP_S = 300;
/** What a folder outside git always leaves out (the Python CLI's `DEFAULT_EXCLUDES`). */
const DEFAULT_EXCLUDES = [".git", ".noclick", "node_modules", ".venv", "venv", "__pycache__", ".DS_Store", ".wrangler",
  ".next", ".turbo", ".cache", ".vercel", ".netlify", "*.pyc"];
/** What one commit through the API carries (`Repo.commit`). */
const MAX_FILES = 1000;
const MAX_BYTES = 50 * 1024 * 1024;

// --- secrets kept out of a deploy (the Python CLI's rule, word for word) ---------------------------------------

const TEMPLATES = [".example", ".sample", ".template", ".dist", ".defaults"];
const SECRET_FILES = [".netrc", ".git-credentials", "id_rsa", "id_ed25519", "id_ecdsa", "credentials.json"];
const SECRET_FOLDERS = [".ssh", ".aws", ".gnupg"];
const PRIVATE_KEY = /-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----/;
const TOKEN_LINE = /(_authToken|npmAuthToken|_auth|_password)\s*[=:]\s*(?!["']?\$\{)\S/;

/** Whether `path` holds a secret: by its name (`.env`, `.dev.vars`, a key, a login), or by what it holds. */
export function secretFile(root: string, path: string): boolean {
  const parts = path.split("/");
  const name = parts.at(-1)!.toLowerCase();
  if (parts.slice(0, -1).some((part) => SECRET_FOLDERS.includes(part.toLowerCase()))) return true;
  if ((name.startsWith(".env") || name.startsWith(".dev.vars")) && !TEMPLATES.some((t) => name.endsWith(t))) return true;
  if (SECRET_FILES.includes(name) || (name.startsWith("service-account") && name.endsWith(".json"))) return true;
  const keyFile = [".pem", ".key"].some((e) => name.endsWith(e));
  if (keyFile || name.endsWith(".p12") || name.endsWith(".pfx") || [".npmrc", ".yarnrc", ".yarnrc.yml"].includes(name)) {
    if (name.endsWith(".p12") || name.endsWith(".pfx")) return true;
    let head: string;
    try {
      head = readFileSync(join(root, path)).subarray(0, 65536).toString("latin1");
    } catch {
      return false;
    }
    return keyFile ? PRIVATE_KEY.test(head) : TOKEN_LINE.test(head);
  }
  return false;
}

const ENV_LINE = /^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=/gm;

/** A file a deploy left out because it looks like a secret, and the names it gives values to (never a value). */
export interface LeftOut {
  path: string;
  names: string[];
}

function nextSteps(item: LeftOut): string[] {
  return item.names.length ? item.names.map((name) => `noclick secret set ${name} --from-env ${name}`)
    : [`noclick secret set NAME --stdin < ${item.path}`];
}

function leftOutOf(root: string, path: string): LeftOut {
  const name = path.split("/").at(-1)!.toLowerCase();
  if (!name.startsWith(".env") && !name.startsWith(".dev.vars")) return { path, names: [] };
  let text = "";
  try {
    text = readFileSync(join(root, path), "utf8");
  } catch {
    // unreadable: named without its keys
  }
  return { path, names: [...new Set([...text.matchAll(ENV_LINE)].map((m) => m[1]!))] };
}

/** The files of `paths` a deploy leaves out because they look like secrets (the Python CLI's `keep_secrets_out`).
 *  One already committed in `head` (`committed`: its files), the commit a deploy ships, refuses it. */
export function keepSecretsOut(root: string, paths: string[], committed: string[] = [], head: string | null = null): LeftOut[] {
  const inHistory = committed.filter((p) => secretFile(root, p));
  if (inHistory.length) {
    const named = inHistory.slice(0, 5).join(", ") + (inHistory.length > 5 ? ` and ${inHistory.length - 5} more` : "");
    throw new CommandError(`${named} looks like a secret and is committed in ${(head ?? "").slice(0, 7)}, the commit this ` +
      "deploy ships, so deploying would put it in the app's repo.", {
      nextStep: `git rm --cached ${inHistory.slice(0, 5).join(" ")}, add it to .gitignore and commit; give the app each value ` +
        "with noclick secret set NAME --from-env NAME, and change the values (they're in this checkout's history).",
      details: { files: inHistory },
    });
  }
  return paths.filter((p) => secretFile(root, p)).map((p) => leftOutOf(root, p));
}

function sayLeftOut(io: Io, left: LeftOut[]): void {
  for (const item of left) {
    io.err(`Left out ${item.path}: it looks like a secret, and a secret never ships in the app's code. Give the app its values with:`);
    for (const step of nextSteps(item)) io.err(`  ${step}`);
  }
}

function leftOutData(left: LeftOut[]): Array<Record<string, unknown>> {
  return left.map((item) => ({ path: item.path, why: "looks like a secret, and a secret never ships in the app's code",
    names: item.names, next_steps: nextSteps(item) }));
}

// --- git --------------------------------------------------------------------------------------------------------

export function git(args: string[], cwd: string, extra: Record<string, string> = {}): Promise<string> {
  return new Promise((done, fail) => {
    execFile("git", args, { cwd, env: { ...host.env, ...extra } as NodeJS.ProcessEnv, maxBuffer: 64 * 1024 * 1024 },
      (err, stdout, stderr) => {
        if ((err as NodeJS.ErrnoException | null)?.code === "ENOENT") {
          fail(new CommandError("git isn't installed.", { nextStep: "noclick deploy --no-git (it ships the folder through the API)" }));
        } else if (err) {
          fail(new CommandError(String(stderr).trim() || `git ${args[0]} failed.`, { details: { git: args, stderr: String(stderr) } }));
        } else done(String(stdout).trim());
      });
  });
}

async function gitRoot(folder: string): Promise<string | null> {
  try {
    return await git(["rev-parse", "--show-toplevel"], folder);
  } catch {
    return null;
  }
}

async function currentBranch(root: string): Promise<string | null> {
  try {
    return await git(["symbolic-ref", "--quiet", "--short", "HEAD"], root);
  } catch {
    return null;
  }
}

/** A one-command remote, so the tokened URL never lands in argv (others' `ps`) or in `.git/config`. */
export function remote(url: string): Record<string, string> {
  return {
    GIT_CONFIG_COUNT: "1", GIT_CONFIG_KEY_0: "remote.noclick-deploy.url", GIT_CONFIG_VALUE_0: url,
    GIT_TERMINAL_PROMPT: "0", GIT_HTTP_LOW_SPEED_LIMIT: "1", GIT_HTTP_LOW_SPEED_TIME: String(GIT_GIVE_UP_S),
  };
}

export async function push(root: string, repo: Repo, sha: string, branch: string): Promise<void> {
  const env = remote(await repo.cloneUrl({ write: true, ttlS: 600 }));
  try {
    await git(["push", "noclick-deploy", `${sha}:refs/heads/${branch}`], root, env);
  } catch (err) {
    const stderr = String((err as CommandError).details?.stderr ?? "");
    if (stderr.includes("Operation too slow")) {
      throw new CommandError(`The repo's git endpoint sent nothing for ${GIT_GIVE_UP_S} seconds, so the push gave up.`, { nextStep: "noclick deploy" });
    }
    if (!stderr.includes("[rejected]")) throw err;
    await git(["fetch", "noclick-deploy", `+refs/heads/${branch}:refs/remotes/noclick/${branch}`], root, env);
    throw new Conflict(`The repo's ${branch} has commits this checkout doesn't (an app service can commit code, too).`,
      { nextStep: `git merge noclick/${branch}, then noclick deploy` });
  }
}

// --- the folder's files ----------------------------------------------------------------------------------------

function globRegex(glob: string): RegExp {
  const body = glob.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
  return new RegExp(`^${body}$`);
}

/** What a folder outside git leaves out: the default excludes, and its own `.gitignore`'s patterns. */
function ignoreGlobs(root: string): RegExp[] {
  const ignore = join(root, ".gitignore");
  const lines = existsSync(ignore) ? readFileSync(ignore, "utf8").split(/\r?\n/) : [];
  const globs: string[] = [];
  for (const line of [...DEFAULT_EXCLUDES, ...lines]) {
    let pattern = line.trim();
    if (!pattern || pattern.startsWith("#")) continue;
    if (pattern.startsWith("!")) {
      throw new CommandError(`.gitignore keeps ${pattern.slice(1)} back in (${pattern}), which a folder outside git can't honour.`,
        { nextStep: "Run git init here (deploy then reads .gitignore as git does), or remove that line." });
    }
    const anchored = pattern.startsWith("/") || pattern.replace(/\/+$/, "").includes("/");
    pattern = pattern.replace(/^\/+|\/+$/g, "");
    globs.push(...(anchored ? [pattern] : [pattern, `*/${pattern}`]));
  }
  return globs.map(globRegex);
}

function excluded(path: string, globs: RegExp[]): boolean {
  const parts = path.split("/");
  return parts.some((_, i) => globs.some((g) => g.test(parts.slice(0, i + 1).join("/"))));
}

/** The files a deploy of `root` outside git carries, by their path from it. */
function folderFiles(root: string): string[] {
  const globs = ignoreGlobs(root);
  const found: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      const path = relative(root, full).split(sep).join("/");
      if (excluded(path, globs)) continue;
      if (entry.isDirectory()) walk(full);
      else if (entry.isFile()) found.push(path);
    }
  };
  walk(root);
  return found.sort();
}

/** Commit `files` from `root` to `branch` of the app's repo; the commit's sha, or null when nothing changed. */
async function commitFiles(repo: Repo, root: string, files: string[], branch: string): Promise<string | null> {
  const bytes = files.reduce((n, f) => n + statSync(join(root, f)).size, 0);
  if (files.length > MAX_FILES || bytes > MAX_BYTES) {
    throw new CommandError(`The folder holds ${files.length} files (${(bytes / 2 ** 20).toFixed(1)} MB), past the ` +
      `${MAX_FILES} files and ${MAX_BYTES / 2 ** 20} MB one deploy of a folder through the API carries.`,
    { nextStep: "Leave out what the build makes (.gitignore it), or run git init and commit, then deploy again: a checkout pushes with git, whatever its size." });
  }
  const staging = mkdtempSync(join(tmpdir(), "noclick-deploy-"));
  try {
    for (const file of files) {
      mkdirSync(dirname(join(staging, file)), { recursive: true });
      copyFileSync(join(root, file), join(staging, file));
    }
    const commit = await repo.commit(staging, { message: `Deploy ${basename(root)} (${files.length} files)`, branch });
    return commit?.sha ?? null;
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
}

/** The folder a link ties: the one holding its `.noclick/`. */
function rootOf(link: links.Link): string {
  return dirname(dirname(link.path));
}

// --- deploy ----------------------------------------------------------------------------------------------------

/** An app's name from a folder's (`My Site` → `my-site`). */
function appName(folder: string): string {
  return basename(folder).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 63) || "app";
}

async function create(name: string, budget: number | undefined): Promise<Project> {
  const repo = await Repo.fromName(name, { createIfMissing: true }).hydrate();
  return await Project.fromName(name, { repo, createIfMissing: true, ...(budget === undefined ? {} : { budgetUsdPerMonth: budget }) }).hydrate();
}

/** The app a deploy ships to, and whether this deploy made it (the Python CLI's rule). */
async function target(values: Values, root: string, linked: boolean): Promise<{ project: Project; made: boolean }> {
  const ref = str(values, "app_ref");
  const flagged = str(values, "app");
  if (ref && flagged && ref !== flagged) throw new CommandError(`Two apps named: ${ref} and --app ${flagged}.`, { nextStep: "Name the app once." });
  const named = ref ?? flagged;
  if (named) {
    try {
      return { project: await lookup(named), made: false };
    } catch (err) {
      if (!(err instanceof NotFound)) throw err;
      if (!on(values, "create")) {
        throw new NotFound(`No app is named '${named}'.`, { nextStep: `noclick deploy --app ${named} --create makes it (and its repo).` });
      }
      return { project: await create(named, num(values, "budget")), made: true };
    }
  }
  if (linked) return { project: (await appOf({}, root)).project, made: false };
  const name = appName(root);
  let existing: Project;
  try {
    existing = await lookup(name);
  } catch (err) {
    if (!(err instanceof NotFound)) throw err;
    return { project: await create(name, num(values, "budget")), made: true };
  }
  throw new CommandError(`This folder isn't linked to an app, and you already have an app named ${existing.name} (${existing.url}).`,
    { nextStep: `Deploy to it: noclick link ${existing.name}, then noclick deploy. Or make a new one: noclick deploy --app <new-name> --create.` });
}

async function branchOf(values: Values, project: Project, checkout: string | null): Promise<string> {
  const given = str(values, "branch");
  if (given) return given;
  if (on(values, "prod")) return project.productionBranch;
  const preview = str(values, "preview");
  if (preview !== undefined) {
    if (preview) return preview;
    const current = checkout ? await currentBranch(checkout) : null;
    return current && current !== project.productionBranch ? current : "preview";
  }
  if (!checkout) return project.productionBranch;
  const current = await currentBranch(checkout);
  if (!current) throw new CommandError("You're not on a branch.", { nextStep: "Pass --prod (the app's production branch), --preview, or --branch <name>." });
  return current;
}

/** Wait for a release (deploy, rollback, promote), or print its operation with `--no-wait`. */
async function settle(values: Values, io: Io, op: Operation<Deployment>, verb: string, extra: Record<string, unknown> = {}): Promise<number> {
  if (on(values, "no_wait")) {
    io.err(`${verb}. Wait for it with: noclick ops wait ${op.id}`);
    answer(io, values, { operation_id: op.id, ...extra }, () => [op.id]);
    return OK;
  }
  io.err(`${verb}…`);
  let deployment: Deployment;
  try {
    deployment = await op.wait({ timeoutS: num(values, "timeout") });
  } catch (err) {
    if (err instanceof OperationFailed && typeof err.details.deployment_id === "string") {
      const lines = await Deployment.fromId(err.details.deployment_id).logs({ kind: "build", limit: 20 });
      for (const line of lines) io.err(`  ${line.message}`);
    }
    throw err;
  }
  answer(io, values, { ...extra, deployment_id: deployment.id, url: deployment.url, production: deployment.production,
    status: deployment.status, warning: deployment.warning, next_step: deployment.nextStep }, () => [String(deployment.url)]);
  if (deployment.warning) {
    io.err(`warning: ${deployment.warning}`);
    if (deployment.nextStep) io.err(`  next step: ${deployment.nextStep}`);
    io.err("It stays live (nothing was rolled back). Go back with: noclick rollback");
    return FAILED;
  }
  io.err(`Ready: ${deployment.production ? "production" : "a preview"}.`);
  return OK;
}

export async function deploy(values: Values, io: Io): Promise<number> {
  if (str(values, "token")) throw new UsageError("npx noclick doesn't take a deploy token yet.", "pip install noclick, then noclick deploy --token <token>");
  const folder = resolve(host.cwd(), str(values, "dir") ?? ".");
  if (!existsSync(folder) || !statSync(folder).isDirectory()) throw new CommandError(`${folder} isn't a folder.`, { nextStep: "Pass --dir the app's folder." });
  const link = links.find(folder);
  const checkout = on(values, "no_git") ? null : await gitRoot(folder);
  const root = checkout ?? (link ? rootOf(link) : null) ?? folder;
  // Everything a deploy refuses is refused before anything is made, set or pushed.
  let dirty = false;
  let files: string[];
  let left: LeftOut[];
  if (checkout) {
    const head = await git(["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], checkout).catch(() => null);
    const committed = head ? (await git(["ls-tree", "-r", "-z", "--name-only", head], checkout)).split("\0").filter(Boolean) : [];
    files = (await git(["ls-files", "-co", "--exclude-standard", "-z"], checkout)).split("\0").filter((p) => p && existsSync(join(checkout, p)));
    left = keepSecretsOut(root, files, committed, head);
    const out = new Set(left.map((item) => item.path));
    files = files.filter((p) => !out.has(p));
    // What git says changed, less what's left out: a checkout whose only change is a secret ships its commit.
    const status = (await git(["status", "--porcelain", "-z", "--untracked-files=all"], checkout)).split("\0");
    for (let i = 0; i < status.length; i++) {
      const entry = status[i]!;
      if (entry.length < 4) continue;
      if (entry[0] === "R" || entry[0] === "C") i++; // its old path follows
      if (!out.has(entry.slice(3))) dirty = true;
    }
    if (dirty && on(values, "only_committed")) {
      throw new CommandError("Your checkout has uncommitted or untracked files, and --only-committed ships the commit alone.",
        { nextStep: "Commit them (or leave out --only-committed to ship the folder as it is)." });
    }
  } else {
    if (on(values, "only_committed")) {
      throw new CommandError(`${root} isn't a git checkout, so there are no commits to ship.`, { nextStep: "Deploy without --only-committed, which ships the folder as it is." });
    }
    files = folderFiles(root);
    left = keepSecretsOut(root, files);
    const out = new Set(left.map((item) => item.path));
    files = files.filter((p) => !out.has(p));
  }
  if (!files.length) throw new CommandError(`There's nothing to deploy: ${root} holds no files.`, { nextStep: "Run noclick deploy in the app's folder (or pass --dir)." });

  const { project, made } = await target(values, root, link !== null);
  if (made) io.err(`Made the app ${project.name} and its repo, with a monthly budget of ${usd(project.budgetUsdPerMonth)} (--budget sets another).`);
  else if (num(values, "budget") !== undefined) await project.update({ budgetUsdPerMonth: num(values, "budget")! });
  const repo = project.repo;
  if (!repo) throw new CommandError(`${project.name} deploys no repo of NoClick's.`, { nextStep: `noclick status --app ${project.name}` });
  const branch = await branchOf(values, project, checkout);
  const production = branch === project.productionBranch;
  io.err(`Deploying ${root} to ${project.name} (${production ? "production" : `a preview of ${branch}`}).`);
  sayLeftOut(io, left);

  let commit: string | null;
  if (checkout && !dirty) {
    commit = await git(["rev-parse", "HEAD"], checkout);
    await push(checkout, repo, commit, branch);
    io.err(`Pushed ${commit.slice(0, 7)} to ${branch}.`);
  } else {
    commit = await commitFiles(repo, root, files, branch);
    io.err(`Shipping the folder as it is (${checkout ? "uncommitted or untracked files" : "not a git checkout"}): ${files.length} files` +
      (commit ? `, committed as ${commit.slice(0, 7)} to ${branch}.` : `, the same as ${branch} already holds.`));
  }
  if (!link || link.appId !== project.id) {
    links.write(project.name, { appId: project.id, apiUrl: resolveCredentials(host.env, profileOf(values)).apiUrl, root });
    io.err(`Linked ${root} to ${project.name} (.noclick/project.json): later commands here act on it.`);
  }
  const op = await project.deploy({ branch, commit: commit ?? undefined });
  return await settle(values, io, op, "Building", { app: { id: project.id, name: project.name }, branch, production, commit, made, files,
    left_out: leftOutData(left) });
}

// --- link ------------------------------------------------------------------------------------------------------

export async function link(values: Values, io: Io): Promise<number> {
  const folder = resolve(host.cwd(), str(values, "dir") ?? ".");
  const ref = str(values, "app_ref") ?? str(values, "app");
  if (!ref) throw new CommandError("Name the app to link this folder to.", { nextStep: "noclick link <app> (its name or id)." });
  let project: Project;
  let made = false;
  try {
    project = await lookup(ref);
  } catch (err) {
    if (!(err instanceof NotFound) || !on(values, "create") || ID.test(ref)) {
      if (err instanceof NotFound) throw new NotFound(`No app is named '${ref}'.`, { nextStep: `noclick link ${ref} --create makes it (and its repo).` });
      throw err;
    }
    project = await create(ref, num(values, "budget"));
    made = true;
  }
  links.write(project.name, { appId: project.id, apiUrl: resolveCredentials(host.env, profileOf(values)).apiUrl, root: folder });
  io.err(`${made ? "Made and linked" : "Linked"} ${folder} to ${project.name}: commands here act on it.`);
  answer(io, values, { app: { id: project.id, name: project.name }, folder, made }, () => [project.url]);
  return OK;
}

export async function unlink(values: Values, io: Io): Promise<number> {
  const folder = resolve(host.cwd(), str(values, "dir") ?? ".");
  const found = links.find(folder);
  if (!found) {
    io.err(`${folder} isn't linked to an app.`);
    answer(io, values, { unlinked: false }, () => []);
    return OK;
  }
  links.remove(rootOf(found));
  io.err(`Unlinked ${rootOf(found)} from ${found.app} (the app is unchanged).`);
  answer(io, values, { unlinked: true, app: { id: found.appId, name: found.app } }, () => []);
  return OK;
}

// --- read ------------------------------------------------------------------------------------------------------

export async function status(values: Values, io: Io): Promise<number> {
  await noteUnclaimed(values, io);
  const { project } = await appOf(values);
  const since = new Date(Date.now() - 86_400_000);
  const [releases, errors, bindings, secrets, settings, usage] = await Promise.all([
    project.deployments({ limit: 5 }), project.logs({ since, level: "error", limit: 20 }), project.bindings(),
    project.secrets.list(), project.settings.list(), project.usage(),
  ]);
  const live = releases.find((d) => d.production) ?? null;
  answer(io, values, {
    app: { id: project.id, name: project.name }, url: project.url, production_branch: project.productionBranch,
    live: live && { id: live.id, commit: live.commit, created_at: live.createdAt, warning: live.warning },
    last_deploy: releases[0] && { id: releases[0].id, branch: releases[0].branch, status: releases[0].status },
    errors_24h: errors.length, bindings: bindings.map((b) => ({ name: b.name, kind: b.kind })), secrets: Object.keys(secrets),
    settings: Object.keys(settings), spend_usd: usage.usd, budget_usd: project.budgetUsdPerMonth,
  }, () => [
    ...OUT.fields([
      `app         ${project.name} (${project.id})`,
      `live        ${live ? `${(live.commit ?? live.id).slice(0, 7)} since ${cell(live.createdAt)}${live.warning ? `: ${live.warning}` : ""}` : "nothing yet: noclick deploy"}`,
      `last deploy ${releases[0] ? `${releases[0].branch}, ${releases[0].status}` : "-"}`,
      `errors      ${errors.length} in the last day${errors.length ? ": noclick logs --level error" : ""}`,
      `bindings    ${bindings.map((b) => `${b.name} (${b.kind})`).join(", ") || "-"}`,
      `secrets     ${Object.keys(secrets).sort().join(", ") || "-"}`,
      `settings    ${Object.keys(settings).sort().join(", ") || "-"}`,
      `spend       ${usd(usage.usd)} this month${project.budgetUsdPerMonth !== null ? ` of its ${usd(project.budgetUsdPerMonth)} budget` : ""}`,
    ]),
    project.url,
  ]);
  return OK;
}

export async function open(values: Values, io: Io): Promise<number> {
  const { project } = await appOf(values);
  let url = project.url;
  const preview = str(values, "preview");
  if (preview !== undefined) {
    const ready = (await project.deployments({ limit: 50 })).filter((d) => d.status === "ready" && !d.production &&
      (!preview || d.branch === preview) && d.branch !== project.productionBranch);
    if (!ready.length) throw new NotFound(`${project.name} has no preview${preview ? ` of ${preview}` : ""} ready.`, { nextStep: "noclick deploy --preview makes one." });
    url = String(ready[0]!.url);
  }
  answer(io, values, { url }, () => [url]);
  return OK;
}

export async function releases(values: Values, io: Io): Promise<number> {
  const { project } = await appOf(values);
  const limit = num(values, "limit") ?? 10;
  const found = await project.deployments({ branch: on(values, "all") ? undefined : project.productionBranch, limit: limit + 1 });
  const shown = found.slice(0, limit);
  if (on(values, "json")) {
    printJson(io, { data: shown.map((d) => ({ id: d.id, branch: d.branch, status: d.status, commit: d.commit, url: d.url ?? null,
      production: d.production, created_at: d.createdAt, warning: d.raw.warning ?? null })), has_more: found.length > limit });
    return OK;
  }
  answer(io, values, {}, () => {
    const message = (d: Deployment) => {
      const first = (d.commitMessage ?? "").split("\n")[0]!;
      return first.length <= 50 ? first : `${first.slice(0, 49)}…`;
    };
    table(io, ["", "ID", "BRANCH", "STATUS", "COMMIT", "CREATED", "MESSAGE"], shown.map((d) => [d.production ? "*" : "", d.id, d.branch,
      d.status, (d.commit ?? "").slice(0, 7), d.createdAt, message(d)]), `${project.name} has no deployments yet: noclick deploy.`,
      `Releases of ${project.name}`);
    return [];
  });
  if (found.length > limit) io.err(`More: noclick releases --limit ${limit * 2}${on(values, "all") ? " --all" : ""}`);
  if (shown.length) io.err("* serves production. Go back to one: noclick rollback <id>");
  return OK;
}

function findRelease(releases: Deployment[], ref: string): Deployment | undefined {
  return releases.find((d) => d.id === ref || (ref.length >= 7 && (d.commit ?? "").startsWith(ref)) || d.url === ref.replace(/\/+$/, ""));
}

export async function rollback(values: Values, io: Io): Promise<number> {
  const { project } = await appOf(values);
  const releases = await project.deployments({ branch: project.productionBranch, limit: 20 });
  const ref = str(values, "release");
  let to: Deployment | undefined;
  if (ref) {
    to = findRelease(releases, ref) ?? (ID.test(ref) ? await Deployment.get(ref) : undefined);
    if (!to) throw new NotFound(`No release of ${project.name} is ${ref}.`, { nextStep: "noclick releases lists them by id and commit." });
  } else {
    const live = releases.findIndex((d) => d.production);
    to = releases.slice(live + 1).find((d) => d.status === "ready");
    if (!to) throw new NotFound(`${project.name} has no earlier release to go back to.`, { nextStep: "noclick releases lists what it has." });
  }
  io.err(`Rolling ${project.name} back to ${(to.commit ?? to.id).slice(0, 7)} (${cell(to.createdAt)}).`);
  return await settle(values, io, await project.rollback(to), "Rolling back");
}

export async function promote(values: Values, io: Io): Promise<number> {
  const { project } = await appOf(values);
  const ref = String(values.preview);
  let to: Deployment | undefined;
  if (ID.test(ref)) to = await Deployment.get(ref);
  else {
    const ready = (await project.deployments({ limit: 50 })).filter((d) => d.status === "ready");
    to = ready.find((d) => d.branch === ref || d.url === ref.replace(/\/+$/, "")) ?? findRelease(ready, ref);
  }
  if (!to) throw new NotFound(`${project.name} has no ready preview of ${ref}.`, { nextStep: `noclick deploy --preview ${ref} makes one; noclick releases --all lists them.` });
  io.err(`Promoting ${to.branch} (${(to.commit ?? "").slice(0, 7)}) to production.`);
  return await settle(values, io, await to.promote({ force: on(values, "force") }), "Promoting");
}

export async function deleteApp(values: Values, io: Io): Promise<number> {
  const { project, link: linked } = await appOf(values);
  const deleteData = on(values, "delete_data");
  const preview = await project.previewDelete({ deleteData });
  const data: Record<string, unknown> = { app: { id: project.id, name: project.name }, preview: preview.raw, deleted: false };
  if (!on(values, "yes")) {
    for (const line of [preview.deletes, ...[...preview.dependsOnIt, ...preview.dataLost].map((l) => `  ${l}`), ...(preview.undo ? [preview.undo] : [])]) io.err(line);
    const command = `noclick delete --app ${project.name}${deleteData ? " --delete-data" : ""} --yes`;
    io.err(`Nothing was deleted. To delete it: ${command}`);
    answer(io, values, data, () => [command]);
    return USAGE;
  }
  const item = await project.delete({ deleteData });
  if (linked && linked.appId === project.id) {
    links.remove(rootOf(linked));
    io.err(`Unlinked ${rootOf(linked)}.`);
  }
  io.err(`Deleted ${project.name}: ${preview.undo ?? "it can't be undone."}`);
  answer(io, values, { ...data, deleted: true, trash_item_id: item.id }, () => [item.id]);
  return OK;
}
