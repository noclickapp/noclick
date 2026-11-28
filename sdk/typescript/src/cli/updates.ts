/**
 * The update notice: one line on stderr, at most once a day, when npm has a newer `noclick` than this one, as the
 * Python CLI says it about PyPI (`noclick/_cli/updates.py`), in the same words.
 *
 * It never delays a command: npm is asked by a process of its own, started at most once a day and never waited on,
 * which writes what it heard to `updates-npm.json` in the config directory; a later command reads that file. Nothing
 * is said when either stream isn't a terminal, in CI, under `--json`, or with `NOCLICK_NO_UPDATE_CHECK` set.
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import { host } from "./host.ts";
import { configDir } from "./store.ts";

export const OFF_ENV = "NOCLICK_NO_UPDATE_CHECK";
export const DAY_MS = 24 * 60 * 60 * 1000;
export const NPM = "npm install -g noclick@latest";
export const FILE = "updates-npm.json";
const REGISTRY_URL = "https://registry.npmjs.org/noclick/latest";

/** What the process that asks npm runs: `node -e <this> <cache file>`. */
const ASK = `const fs = require("node:fs"); const path = process.argv[1];
fetch(${JSON.stringify(REGISTRY_URL)}, { signal: AbortSignal.timeout(5000) }).then((r) => r.json()).then((body) => {
  let seen = {}; try { seen = JSON.parse(fs.readFileSync(path, "utf8")); } catch {}
  if (typeof body.version === "string") fs.writeFileSync(path, JSON.stringify({ ...seen, latest: body.version }) + "\\n");
}).catch(() => {});`;

/** Whether `latest` is a later release than `current` (a pre-release is never offered). */
export function newer(latest: string, current: string): boolean {
  const parts = (v: string) => (/^\d+(\.\d+)*$/.test(v) ? v.split(".").map(Number) : null);
  const a = parts(latest);
  const b = parts(current);
  if (!a || !b) return false;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if ((a[i] ?? 0) !== (b[i] ?? 0)) return (a[i] ?? 0) > (b[i] ?? 0);
  }
  return false;
}

export const words = (latest: string, current: string, how: string) =>
  `A newer noclick is out: ${latest} (you have ${current}). Update: ${how}`;

type Seen = { checked_at?: number; latest?: string; told_at?: number };

function read(path: string): Seen {
  try {
    return JSON.parse(readFileSync(path, "utf8")) as Seen;
  } catch {
    return {};
  }
}

function write(path: string, seen: Seen): void {
  try {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, `${JSON.stringify(seen)}\n`);
  } catch {
    // a config directory it can't write: nothing said, nothing asked again
  }
}

const withinADay = (at: unknown, now: number) => typeof at === "number" && now - at * 1000 < DAY_MS;

/** The line to say after a command, if any; asks npm again when what it heard is a day old. Times are kept in
 *  seconds, as the Python CLI keeps them in the same file. */
export function notice(argv: string[], options: {
  current: string; how: string; terminals: boolean; env?: Record<string, string | undefined>; now?: number;
}): string | null {
  const env = options.env ?? host.env;
  if (!options.terminals || env.CI || env[OFF_ENV] || argv.includes("--json")) return null;
  const path = join(configDir(env), FILE);
  const now = options.now ?? Date.now();
  const seen = read(path);
  if (!withinADay(seen.checked_at, now)) {
    seen.checked_at = now / 1000; // asked at most once a day, whether or not it answers
    write(path, seen);
    host.detached(["-e", ASK, path]);
  }
  if (typeof seen.latest !== "string" || !newer(seen.latest, options.current) || withinADay(seen.told_at, now)) return null;
  seen.told_at = now / 1000;
  write(path, seen);
  return words(seen.latest, options.current, options.how);
}
