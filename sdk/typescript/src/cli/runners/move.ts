/**
 * Moving a coding session from this machine, as the Python CLI's `agents move …` steps are. The agent in the
 * session moves itself (the guide at noclick.com/move.md): these commands only carry what it chose, with the move's
 * own key, kept in a file only you read and never printed.
 */

import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { basename, dirname, join, relative, resolve, sep } from "node:path";
import { gzipSync } from "node:zlib";

import { AgentMove } from "../../agentMove.ts";
import { API_URL_ENV, DEFAULT_BASE_URL, NoClick } from "../../client.ts";
import type { JsonObject } from "../../object.ts";
import type { Values } from "../args.ts";
import { OK } from "../exits.ts";
import { host } from "../host.ts";
import { type Io, printJson } from "../output.ts";
import { CommandError, configDir } from "../store.ts";
import { on, str } from "./kit.ts";
import { size } from "./resources.ts";
import { git, remote } from "./ship.ts";

const MOVE_KEY_FILE = "move.json";
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const home = (path: string) => (path === "~" || path.startsWith("~/") ? join(host.env.HOME || homedir(), path.slice(1)) : path);

const keyPath = () => join(configDir(host.env), MOVE_KEY_FILE);

/** The move this machine redeemed, through a client holding the move's own key. */
async function moving(): Promise<AgentMove> {
  const path = keyPath();
  if (!existsSync(path)) {
    throw new CommandError("No move is under way here.",
      { nextStep: "Redeem the code your prompt gave: noclick agents move redeem --code nc_move_..." });
  }
  const saved = JSON.parse(readFileSync(path, "utf8")) as { key: string; api_url: string };
  return await AgentMove.current({ client: new NoClick({ apiKey: saved.key, baseUrl: saved.api_url, fetch: host.fetch }) });
}

const object = (value: unknown): JsonObject => (value && typeof value === "object" ? (value as JsonObject) : {});
const list = (value: unknown): JsonObject[] => (Array.isArray(value) ? (value as JsonObject[]) : []);

function printMove(io: Io, move: AgentMove, json: boolean): void {
  const raw = move.raw;
  if (json) {
    printJson(io, raw);
    return;
  }
  const arrived = object(raw.arrived);
  const lands = object(raw.lands_as);
  io.out(`${raw.status}: ${lands.name ?? ""} -> ${lands.cwd ?? ""}`);
  const names = (key: string) => list(arrived[key]).map((x) => String(x.name)).join(", ");
  const rows: [string, unknown][] = [
    ["session", object(arrived.session).messages], ["repo", object(arrived.repo).branch], ["files", list(arrived.files).length],
    ["secrets", names("secrets")], ["mcp servers", names("mcp_servers")], ["skills", names("skills")], ["memories", names("memories")],
  ];
  for (const [label, value] of rows) if (value) io.out(`  ${label.padEnd(12)} ${value}`);
  for (const step of list(raw.steps)) {
    io.out(`  step ${String(step.name).padEnd(12)} ${step.status}${step.error ? `: ${step.error}` : ""}`);
  }
  if (raw.agent_id) io.out(`  agent ${raw.agent_id}, conversation ${raw.conversation}`);
}

// --- a gzipped tar of files, as the API takes a session's or a skill's -----------------------------------------

function header(name: string, bytes: number, mtime: number): Buffer {
  let [prefix, rest] = ["", name];
  if (Buffer.byteLength(name) > 100) {
    const cut = name.lastIndexOf("/", 155);
    [prefix, rest] = [name.slice(0, cut), name.slice(cut + 1)];
    if (cut < 0 || Buffer.byteLength(rest) > 100) throw new CommandError(`${name} is too long a path to carry.`);
  }
  const block = Buffer.alloc(512);
  const put = (text: string, at: number, width: number) => block.write(text, at, width, "utf8");
  const octal = (n: number, width: number) => n.toString(8).padStart(width - 1, "0");
  put(rest, 0, 100);
  put(octal(0o644, 8), 100, 8);
  put(octal(0, 8), 108, 8);
  put(octal(0, 8), 116, 8);
  put(octal(bytes, 12), 124, 12);
  put(octal(mtime, 12), 136, 12);
  put("        ", 148, 8);
  put("0", 156, 1);
  put("ustar\x0000", 257, 8);
  put(prefix, 345, 155);
  let sum = 0;
  for (const byte of block) sum += byte;
  put(`${octal(sum, 7)}\0`, 148, 8);
  return block;
}

/** `paths` under `root` as a gzipped tar, each named by its path under `root`. */
export function tarGz(root: string, paths: string[]): Uint8Array {
  const parts: Buffer[] = [];
  for (const rel of paths) {
    const source = join(root, rel);
    if (!existsSync(source) || !statSync(source).isFile()) {
      throw new CommandError(`${source} isn't a file.`, { nextStep: "Name the session's own files, relative to the harness's home." });
    }
    const data = readFileSync(source);
    parts.push(header(rel.split(sep).join("/"), data.length, Math.floor(statSync(source).mtimeMs / 1000)), data,
      Buffer.alloc((512 - (data.length % 512)) % 512));
  }
  parts.push(Buffer.alloc(1024));
  return new Uint8Array(gzipSync(Buffer.concat(parts)));
}

// --- the steps ----------------------------------------------------------------------------------------------------

export async function redeem(values: Values, io: Io): Promise<number> {
  const apiUrl = (str(values, "api_url") || host.env[API_URL_ENV] || DEFAULT_BASE_URL).replace(/\/+$/, "");
  const key = await AgentMove.redeem(String(values.code), {
    host: str(values, "host") ?? host.hostname(), client: new NoClick({ apiKey: "", baseUrl: apiUrl, fetch: host.fetch }),
  });
  const path = keyPath();
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  writeFileSync(path, `${JSON.stringify({ key, api_url: apiUrl }, null, 2)}\n`, { mode: 0o600 });
  chmodSync(path, 0o600);
  io.err(`Redeemed: the move's key is in ${path} (only you can read it; it reaches only this move).`);
  return OK;
}

export async function status(values: Values, io: Io): Promise<number> {
  printMove(io, await moving(), on(values, "json"));
  return OK;
}

export async function source(values: Values, io: Io): Promise<number> {
  const move = await (await moving()).setSource({
    harness: String(values.harness), host: str(values, "host") ?? host.hostname(), cwd: resolve(host.cwd(), str(values, "cwd") ?? "."),
    cliVersion: str(values, "cli_version"), sessionId: str(values, "session_id"), title: str(values, "title"),
    model: str(values, "model"), effort: str(values, "effort"), speed: str(values, "speed"),
  });
  printMove(io, move, false);
  return OK;
}

export async function session(values: Values, io: Io): Promise<number> {
  const root = resolve(home(String(values.home)));
  const move = await (await moving()).uploadSession(tarGz(root, values.files as string[]),
    { harness: String(values.harness), cwd: String(values.cwd), sessionId: str(values, "session_id") });
  const got = object(object(move.raw.arrived).session);
  io.out(`Read ${got.messages} messages and ${got.tool_calls} tool calls: ${got.title}`);
  return OK;
}

/** HEAD plus every uncommitted and untracked (not ignored) change, as one commit made with a temporary index, so the
 *  checkout, index and stash never change. HEAD itself when there's nothing uncommitted. */
async function workCommit(root: string, at: string): Promise<string> {
  const head = await git(["rev-parse", "HEAD"], root);
  const temp = mkdtempSync(join(tmpdir(), "noclick-move-"));
  let tree: string;
  try {
    const env = { GIT_INDEX_FILE: join(temp, "index") };
    await git(["read-tree", "HEAD"], root, env);
    await git(["add", "-A"], root, env);
    tree = await git(["write-tree"], root, env);
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
  if (tree === (await git(["rev-parse", "HEAD^{tree}"], root))) return head;
  return await git(["commit-tree", tree, "-p", head, "-m", `Uncommitted work moved from ${at}`], root);
}

export async function repo(values: Values, io: Io): Promise<number> {
  let root: string;
  try {
    root = await git(["rev-parse", "--show-toplevel"], resolve(host.cwd(), str(values, "path") ?? "."));
  } catch (err) {
    if (!(err instanceof CommandError) || !err.details?.stderr) throw err;
    throw new CommandError("This folder isn't a git repository.",
      { nextStep: "Send its files with noclick agents move file, or make it one (git init, then commit), then run this again." });
  }
  const commit = await workCommit(root, str(values, "host") ?? host.hostname());
  const pushed = await (await moving()).repo({ name: str(values, "name") ?? basename(root), branch: str(values, "branch") });
  // The move's own branch: a move run again replaces what its last run pushed.
  await git(["push", "noclick-deploy", `+${commit}:refs/heads/${pushed.branch}`], root, remote(String(pushed.url)));
  io.out(`Pushed ${commit.slice(0, 7)} to ${pushed.name}, branch ${pushed.branch}: it works in ${pushed.cwd}.`);
  return OK;
}

export async function file(values: Values, io: Io): Promise<number> {
  const path = home(String(values.path));
  const move = await (await moving()).putFile(str(values, "to") ?? basename(path), new Uint8Array(readFileSync(path)));
  io.out(`Carried ${path} (${size(statSync(path).size)}); ${list(object(move.raw.arrived).files).length} in all.`);
  return OK;
}

function dotenv(path: string): Record<string, string> {
  const found: Record<string, string> = {};
  for (let line of readFileSync(path, "utf8").split(/\r?\n/)) {
    line = line.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    if (line.startsWith("export ")) line = line.slice(7);
    const at = line.indexOf("=");
    let value = line.slice(at + 1).trim();
    if (value.length >= 2 && value[0] === value.at(-1) && (value[0] === "'" || value[0] === '"')) value = value.slice(1, -1);
    found[line.slice(0, at).trim()] = value;
  }
  return found;
}

/** Each secret as name:kind:to, as the person read it, once they said yes in the session; never a value. */
export async function consent(values: Values, io: Io): Promise<number> {
  const entries = (values.secrets as string[]).map((given) => {
    const at = [given.indexOf(":"), given.indexOf(":", given.indexOf(":") + 1)];
    const parts = at[0]! < 0 || at[1]! < 0 ? [] : [given.slice(0, at[0]), given.slice(at[0]! + 1, at[1]), given.slice(at[1]! + 1)];
    if (parts.length !== 3 || !parts.every((p) => p.trim())) {
      throw new CommandError(`'${given}' isn't name:kind:to.`, { nextStep: "Like linear-token:Linear API key:env LINEAR_API_KEY." });
    }
    return { name: parts[0]!.trim(), kind: parts[1]!.trim(), to: parts[2]!.trim() };
  });
  const move = await (await moving()).consent(entries, { confirmed: on(values, "yes") });
  io.out(`The person said yes to: ${list(object(move.raw.arrived).consent).map((e) => e.name).join(", ")}`);
  return OK;
}

/** The value comes from a variable or a file the session reads, never printed. */
export async function secret(values: Values, io: Io): Promise<number> {
  let value: string | undefined;
  const fromEnv = str(values, "from_env");
  const fromDotenv = str(values, "from_dotenv");
  if (fromEnv !== undefined) {
    value = host.env[fromEnv];
    if (!value) throw new CommandError(`${fromEnv} isn't set here.`);
  } else if (fromDotenv !== undefined) {
    const where = str(values, "dotenv") ?? ".env";
    value = dotenv(where)[fromDotenv];
    if (!value) throw new CommandError(`No value for ${fromDotenv} in ${where}.`);
  } else value = readFileSync(home(String(values.from_file)), "utf8");
  const toFile = str(values, "to_file");
  const to: JsonObject = str(values, "to_env") ? { env: str(values, "to_env")! }
    : toFile ? { file: toFile, ...(str(values, "mode") ? { mode: str(values, "mode")! } : {}) }
    : str(values, "to_model") ? { model: str(values, "to_model")! } : {};
  await (await moving()).putSecret(String(values.name), value, { to });
  io.out(`Carried the secret ${values.name} (sealed; its value never shown).`);
  return OK;
}

export async function setup(values: Values, io: Io): Promise<number> {
  const commands = values.commands as string[];
  await (await moving()).setSetup(commands);
  io.out(`The copy's sandbox runs ${commands.length} setup command(s) as it starts.`);
  return OK;
}

export async function checkout(values: Values, io: Io): Promise<number> {
  const url = String(values.url);
  const move = await (await moving()).setCheckout(url, String(values.branch),
    { path: str(values, "path"), secret: str(values, "secret"), username: str(values, "username") });
  io.out(`The copy checks out ${url} at ${values.branch}, in ${object(move.raw.lands_as).cwd ?? ""}.`);
  return OK;
}

export async function planLink(_values: Values, io: Io): Promise<number> {
  const link = await (await moving()).planLink();
  io.out(link.url ? String(link.url) : `The ${link.integration} plan is connected already.`);
  return OK;
}

export async function mcp(values: Values, io: Io): Promise<number> {
  const headersFile = str(values, "headers_file");
  const headers = headersFile ? JSON.parse(readFileSync(headersFile, "utf8")) : {};
  if (!headers || typeof headers !== "object" || Array.isArray(headers)
    || !Object.values(headers).every((v) => typeof v === "string" || (v !== null && typeof v === "object"))) {
    throw new CommandError("--headers-file holds one JSON object of header names and their values (text, or {\"secret\": name} for a carried secret's).");
  }
  await (await moving()).addMcpServer(String(values.name), String(values.url),
    { transport: (str(values, "transport") ?? "http") as "http" | "sse", headers });
  io.out(`Carried the MCP server ${values.name} (${values.url}).`);
  return OK;
}

function filesUnder(folder: string): string[] {
  const found: string[] = [];
  const walk = (at: string) => {
    for (const entry of readdirSync(at, { withFileTypes: true })) {
      const path = join(at, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (entry.isFile()) found.push(relative(folder, path));
    }
  };
  walk(folder);
  return found.sort();
}

export async function skill(values: Values, io: Io): Promise<number> {
  const folder = resolve(home(String(values.folder)));
  if (!existsSync(join(folder, "SKILL.md"))) throw new CommandError(`${folder} has no SKILL.md.`, { nextStep: "Name a skill's own folder." });
  const files = filesUnder(folder);
  const name = str(values, "name") ?? basename(folder);
  await (await moving()).addSkill(name, tarGz(folder, files));
  io.out(`Carried the skill ${name} (${plural(files.length, "file")}).`);
  return OK;
}

const text = async (path: string) => (path === "-" ? await host.stdin() : readFileSync(home(path), "utf8"));

export async function memory(values: Values, io: Io): Promise<number> {
  await (await moving()).addMemory(String(values.name), await text(String(values.file)), { description: String(values.description) });
  io.out(`Carried the memory ${values.name}.`);
  return OK;
}

export async function note(values: Values, io: Io): Promise<number> {
  await (await moving()).setNote(await text(String(values.file)));
  io.out("Carried the handoff note.");
  return OK;
}

export async function instructions(values: Values, io: Io): Promise<number> {
  await (await moving()).setInstructions(await text(String(values.file)));
  io.out("Carried its instructions.");
  return OK;
}

export async function finish(values: Values, io: Io): Promise<number> {
  const move = await (await moving()).finish({
    name: str(values, "name"), model: str(values, "model"), modelConnection: str(values, "model_connection"),
    harness: str(values, "harness"), none: values.none as ("mcp_servers" | "skills")[] | undefined,
  });
  if (move.raw.question) { // asked before anything was made: the move's key answers it
    if (on(values, "json")) printJson(io, move.raw);
    else io.out(String(move.raw.question));
    return OK;
  }
  if (existsSync(keyPath())) unlinkSync(keyPath());
  printMove(io, move, on(values, "json"));
  return OK;
}
