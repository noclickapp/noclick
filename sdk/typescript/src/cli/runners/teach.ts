/**
 * Teach, as the Python CLI's `noclick/_cli/parts/teach.py` is: `noclick docs` and `noclick skill` print the guides
 * and skills as Markdown for an agent's context (no key needed), and `noclick mcp` sets NoClick's MCP server up in a
 * coding agent's harness.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

import { type DocHit, Docs } from "../../docs.ts";
import { NotFound } from "../../errors.ts";
import type { Values } from "../args.ts";
import { OK } from "../exits.ts";
import { host } from "../host.ts";
import { type Io, printJson } from "../output.ts";
import { num, on, str, table } from "./kit.ts";

const MCP_URL_ENV = "NOCLICK_MCP_URL";
const DEFAULT_MCP_URL = "https://mcp.noclick.com";
const SERVER = "noclick";

async function printDoc(io: Io, id: string): Promise<number> {
  let doc;
  try {
    doc = await Docs.read(id);
  } catch (err) {
    if (!(err instanceof NotFound)) throw err;
    const hits = await Docs.search(id.split(":").slice(-1)[0]!.replace(/-/g, " "), { limit: 5 });
    throw new NotFound(`No doc is called '${id}'.`, {
      nextStep: hits.length ? `Read one of these: ${hits.map((h) => `noclick docs ${h.id}`).join(", ")}` : "List them with: noclick docs",
    });
  }
  io.out(`# ${doc.title}\n\n${doc.text.trim()}`);
  if (doc.sections.length) {
    io.err(`Its sections, one at a time: noclick docs ${doc.sections[0]} (${doc.sections.length} in all: `
      + `${doc.sections.slice(0, 6).join(", ")}${doc.sections.length > 6 ? ", …" : ""})`);
  }
  if (doc.url) io.err(`On the web: ${doc.url}`);
  return OK;
}

function printHits(io: Io, hits: DocHit[], json: boolean, empty: string, how: string): number {
  if (json) {
    printJson(io, hits.map((h) => h.raw));
    return OK;
  }
  table(io, ["ID", "TITLE", "ABOUT"], hits.map((h) => [h.id, h.title, h.snippet.slice(0, 90)]), empty);
  if (hits.length) io.err(how);
  return OK;
}

export async function docs(values: Values, io: Io): Promise<number> {
  const search = str(values, "search");
  const kind = str(values, "kind");
  const json = on(values, "json");
  if (search) {
    return printHits(io, await Docs.search(search, { kind, limit: num(values, "limit") ?? 10 }), json,
      `Nothing found for '${search}'.`, "Read one with: noclick docs <id>");
  }
  const topic = str(values, "topic");
  if (topic) return await printDoc(io, topic);
  return printHits(io, await Docs.search(undefined, { kind: kind ?? "guide" }), json, "No guides.",
    "Read one with: noclick docs <id> (or its name: noclick docs apps). Search them with noclick docs --search <words>; the task playbooks are noclick skill.");
}

export async function skill(values: Values, io: Io): Promise<number> {
  const name = str(values, "name");
  if (name) return await printDoc(io, name.includes(":") ? name : `skill:${name}`);
  return printHits(io, await Docs.search(undefined, { kind: "skill" }), on(values, "json"), "No skills.",
    "Read one with: noclick skill <name> (its id without skill:).");
}

/** Add `entry` as `SERVER` under `key` in the JSON file at `path`; false when it holds one already. */
function mergeJson(path: string, key: string, entry: Record<string, unknown>): boolean {
  const text = existsSync(path) ? readFileSync(path, "utf8") : "";
  const data = (text.trim() ? JSON.parse(text) : {}) as Record<string, Record<string, unknown>>;
  const servers = (data[key] ??= {});
  if (SERVER in servers) return false;
  servers[SERVER] = entry;
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(data, null, 2)}\n`);
  return true;
}

export async function mcp(values: Values, io: Io): Promise<number> {
  const url = host.env[MCP_URL_ENV] || DEFAULT_MCP_URL;
  const keyEnv = on(values, "oauth") ? null : (str(values, "key_env") ?? "NOCLICK_API_KEY");
  const harness = str(values, "harness");
  const dir = str(values, "dir") ?? ".";
  let path: string;
  let key = "";
  let entry: Record<string, unknown> = {};
  let text: string | null = null;
  if (harness === "claude") {
    entry = { type: "http", url, ...(keyEnv ? { headers: { Authorization: `Bearer \${${keyEnv}}` } } : {}) };
    [path, key] = [join(dir, ".mcp.json"), "mcpServers"];
  } else if (harness === "cursor") {
    entry = { url, ...(keyEnv ? { headers: { Authorization: `Bearer \${env:${keyEnv}}` } } : {}) };
    [path, key] = [join(dir, ".cursor", "mcp.json"), "mcpServers"];
  } else if (harness === "codex") {
    path = join(host.env.CODEX_HOME || join(host.env.HOME || homedir(), ".codex"), "config.toml");
    text = [`[mcp_servers.${SERVER}]`, `url = "${url}"`, ...(keyEnv ? [`bearer_token_env_var = "${keyEnv}"`] : [])].join("\n") + "\n";
  } else {
    printJson(io, { url, auth: keyEnv ? { header: "Authorization", value: `Bearer $${keyEnv}` } : "oauth" });
    return OK;
  }
  const shown = text ?? `${JSON.stringify({ [key]: { [SERVER]: entry } }, null, 2)}\n`;
  if (!on(values, "install")) {
    io.out(shown.trimEnd());
    io.err(`That's ${path}'s entry for NoClick. Pass --install to add it there.`);
  } else if (text !== null) {
    const held = existsSync(path) ? readFileSync(path, "utf8") : "";
    if (held.includes(`[mcp_servers.${SERVER}]`)) io.err(`${path} has a ${SERVER} server already: nothing changed.`);
    else {
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, held + (held && !held.endsWith("\n\n") ? "\n" : "") + text);
      io.err(`Added NoClick to ${path}.`);
    }
  } else if (mergeJson(path, key, entry)) io.err(`Added NoClick to ${path}.`);
  else io.err(`${path} has a ${SERVER} server already: nothing changed.`);
  if (keyEnv) {
    const setHere = Boolean(host.env[keyEnv]);
    io.err(`It signs in with the key in ${keyEnv} as the harness starts (the file names the variable, never the key)`
      + `${setHere ? "" : `: set ${keyEnv} where the harness runs (noclick setup or login keeps it for this CLI only)`}.`);
  } else io.err("The harness signs in to NoClick in a browser the first time it connects.");
  io.err("Restart the harness (or start a new session) to load it.");
  return OK;
}
