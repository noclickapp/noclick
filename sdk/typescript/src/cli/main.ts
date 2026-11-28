/**
 * The `noclick` command (`npx noclick`): the same commands as the Python CLI's (`pip install noclick`), run from the
 * same spec. A curated command (the manifest's) runs what `register` was given for it; every `/v1` operation is a
 * command of its own; `api`, `describe` and `help` are built in.
 *
 * The key comes from `NOCLICK_API_KEY` when it's set, else from what `noclick login` stored for the profile in a
 * file (`--profile` or `NOCLICK_PROFILE`; the config directory `NOCLICK_CONFIG_DIR`, else `~/.config/noclick`).
 */

import { API_KEY_ENV, configure } from "../client.ts";
import { NoClickError } from "../errors.ts";
import { asUser } from "../scope.ts";
import { VERSION } from "../version.ts";
import { type ArgSpec, type FlagSpec, type Values, UsageError, helpText, parse } from "./args.ts";
import { screen } from "./helpscreen.ts";
import { commandsFor, runApi, runDescribe, runHelp, runOperation } from "./commands.ts";
import * as output from "./output.ts";
import type { Io } from "./output.ts";
import { host } from "./host.ts";
import { find as findLink } from "./link.ts";
import * as screens from "./screens.ts";
import * as style from "./style.ts";
import { RUNNERS } from "./runners/index.ts";
import { type Command, load } from "./spec.ts";
import { PROFILE_ENV, readProfiles, signedIn } from "./store.ts";

export type Run = (values: Values, io: Io) => number | Promise<number>;

const curated = new Map<string, Run>();

/** Give a curated command (one the manifest lists, by its path) what it runs. */
export function register(path: string[], run: Run): void {
  if (!load().curated(path)) throw new Error(`noclick ${path.join(" ")} isn't in the manifest: add it there first.`);
  curated.set(path.join(" "), run);
}

register(["api"], (values, io) => runApi(io, values));
register(["describe"], (values, io) => runDescribe(io, values));
register(["help"], (values, io) => runHelp(io, values));

/** The key the next command signs in with: `NOCLICK_API_KEY`, else the profile's stored key on its API. */
export function signInWith(profile: string): void {
  const creds = signedIn(host.env, profile);
  configure({ apiKey: creds.key!, baseUrl: creds.apiUrl, fetch: host.fetch });
}

host.signIn = signInWith;
for (const [path, run] of Object.entries(RUNNERS)) register(path.split(" "), run);

const GLOBALS: FlagSpec[] = [
  { flag: "--profile", dest: "profile", type: "string" },
  { flag: "--version", dest: "version", type: "bool" },
];

function curatedSpecs(command: Command): { flags: (FlagSpec & { help?: string })[]; args: (ArgSpec & { help?: string })[] } {
  return { flags: [...command.flags.map((f) => ({ ...f, type: f.type })), ...GLOBALS], args: command.args };
}

const EXITS = "Exit status: 0 done, 1 failed, 2 the command line was wrong, 3 waiting on a person (a link says where), "
  + "4 refused by a limit, a price or a policy, 124 a wait ran out, 130 Ctrl-C.";

/** `noclick --help`: the curated commands by section, the API's areas as one line (each of them with `--all`). */
function topHelp(io: Io, all: boolean): number {
  const spec = load();
  const areas = all ? new Map([...spec.areas()].map(([area, ops]) => [area, ops.length])) : null;
  const options = [...spec.manifest.globals, { flag: "-h, --help", help: "Show this help (--all lists every API area)." }];
  if (style.OUT.on) {
    io.out(screen(style.OUT, {
      usage: "noclick [OPTIONS] <command> ...", description: "The NoClick platform from your terminal.",
      middle: screens.commands(spec.manifest.screens, areas, style.OUT).split("\n"),
      sections: [["Options", options.map((o) => [o.flag, o.help ?? ""] as [string, string])]],
      notes: `${EXITS} Docs: https://noclick.com/docs/guide/cli (noclick ${VERSION})`,
    }));
    return output.OK;
  }
  io.out([
    `usage: noclick [--profile <string>] [--version] <command> ...   (noclick ${VERSION})`, "",
    "The NoClick platform from your terminal.", "",
    screens.commands(spec.manifest.screens, areas), "",
    "flags:", ...options.map((o) => `  ${o.flag.padEnd(24)} ${o.help ?? ""}`), "",
    `${EXITS} Docs: https://noclick.com/docs/guide/cli`,
  ].join("\n"));
  return output.OK;
}

/** `noclick` alone: what it is and what to run first; signed in, who you are and the folder's app. */
function firstScreen(io: Io, profile: string): number {
  const login = readProfiles(host.env)[profile];
  const said = screens.signedIn(login?.store ? login.email : null, host.env[API_KEY_ENV] ? API_KEY_ENV : undefined);
  let linked: string | null = null;
  try {
    linked = said ? findLink(host.cwd())?.app ?? null : null;
  } catch {
    linked = null;
  }
  io.out(screens.first(load().manifest.screens, said, linked, style.OUT));
  return output.OK;
}

/** Whether `path` is a group of curated commands (`agents`, `agents move`). */
function isGroup(path: string[]): boolean {
  return load().commands.some((c) => c.path.length > path.length && path.every((w, i) => c.path[i] === w));
}

/** `rest` (the command's words) with its aliases spelled out: `noclick ls` is `noclick resources`, and `ls` under a
 *  group that has `list` and no `ls` of its own is `list`. */
function unalias(rest: string[]): void {
  const spec = load();
  const { top, group } = spec.manifest.screens.aliases;
  rest[0] = top[rest[0]!] ?? rest[0]!;
  const meant = rest[1] === undefined ? undefined : group[rest[1]];
  if (meant === undefined) return;
  const names = new Set([
    ...spec.commands.filter((c) => c.path.length > 1 && c.path[0] === rest[0]).map((c) => c.path[1]!),
    ...(spec.areas().get(rest[0]!) ?? []).map((op) => op.command),
  ]);
  if (!names.has(rest[1]!) && names.has(meant)) rest[1] = meant;
}

/** `words` naming no command: the closest ones there are, exit 2. */
function unknownCommand(io: Io, words: string[]): number {
  const spec = load();
  const areas = spec.areas();
  const within: string[] = [];
  while (within.length < words.length - 1 && isGroup([...within, words[within.length]!])) within.push(words[within.length]!);
  if (!within.length && words.length > 1 && areas.has(words[0]!)) within.push(words[0]!);
  const curated = [...new Set(spec.commands
    .filter((c) => c.path.length > within.length && within.every((w, i) => c.path[i] === w))
    .map((c) => c.path[within.length]!))];
  const others = within.length > 1 ? [] : within.length ? (areas.get(within[0]!) ?? []).map((op) => op.command) : [...areas.keys()];
  io.err(screens.unknown(words[within.length]!, within, curated, others.filter((n) => !curated.includes(n)), style.ERR));
  return output.USAGE;
}

/** Run the `noclick` command; returns its exit status. */
export async function main(
  argv: string[], given: Io = output.processIo, options: { signIn?: (profile: string) => void } = {},
): Promise<number> {
  const terminal = given.terminal?.() ?? { out: false, err: false, columns: 100 };
  style.configure(style.modeIn(argv), terminal, host.env, () => terminal.columns);
  // A note for a person (stderr) reads as what it is: a check for what's done, an arrow for a step, the rest dim.
  const io: Io = style.ERR.on ? { ...given, err: (line) => given.err(style.ERR.note(line)) } : given;
  const signIn = options.signIn ?? signInWith;
  const spec = load();
  let profile = host.env[PROFILE_ENV] || "default";
  const rest = [...argv];
  // Global flags before the command.
  while (rest[0]?.startsWith("-")) {
    const flag = rest.shift()!;
    if (flag === "--version") {
      io.out(`noclick ${VERSION}`);
      return output.OK;
    }
    if (flag === "-h" || flag === "--help") return topHelp(io, argv.includes("--all"));
    if (flag === "--all") continue;
    if (flag === "--color") {
      const mode = rest.shift();
      if (!style.MODES.includes(mode as style.Mode)) {
        return output.report(io, new UsageError(`--color is one of ${style.MODES.join(", ")}, not ${mode}.`, "noclick --help"), { json: false });
      }
      continue;
    }
    if (flag.startsWith("--color=")) continue;
    if (flag === "--profile") profile = rest.shift() ?? profile;
    else if (flag.startsWith("--profile=")) profile = flag.slice(10);
    else return output.report(io, new UsageError(`No global flag ${flag}.`, "noclick --help"), { json: false });
  }
  if (!rest.length) return firstScreen(io, profile);
  unalias(rest);
  const json = rest.includes("--json");
  try {
    // The longest curated path the words name, else an operation, else an area's list.
    const words = rest.filter((w) => !w.startsWith("-"));
    for (let n = Math.min(3, words.length); n > 0; n--) {
      const path = words.slice(0, n);
      if (rest.slice(0, n).join(" ") !== path.join(" ")) continue;
      const command = spec.curated(path);
      if (!command) continue;
      const usage = `noclick ${path.join(" ")}`;
      const { flags, args } = curatedSpecs(command);
      const values = parse(rest.slice(n), flags, args, usage, command.one_of);
      if (values.help) {
        io.out(helpText(usage, command.summary, flags, args, command.examples, command.notes));
        return output.OK;
      }
      const run = curated.get(path.join(" "));
      if (!run) {
        throw new UsageError(`${usage} isn't in npx noclick yet.`, `pip install noclick, then ${usage}`);
      }
      if (typeof values.profile === "string") profile = values.profile;
      values.profile = profile;
      if (command.auth) signIn(profile);
      const user = values.user;
      return await (typeof user === "string" ? asUser(user, () => run(values, io)) : run(values, io));
    }
    const [area, name] = rest;
    const op = name ? spec.find(area!, name) : null;
    if (op) {
      if (!rest.slice(2).some((w) => w === "-h" || w === "--help")) signIn(profile);
      return await runOperation(io, op, rest.slice(2));
    }
    if (spec.areas().has(area!) && (!name || name.startsWith("-"))) return runHelp(io, { words: [area!] });
    if (isGroup(words)) return runHelp(io, { words });
    return unknownCommand(io, words);
  } catch (err) {
    if (err instanceof NoClickError || err instanceof UsageError) {
      return output.report(io, err, { json, commands: commandsFor(spec) });
    }
    if ((err as NodeJS.ErrnoException)?.code === "ENOENT") {
      return output.report(io, { type: "command_error", message: (err as Error).message }, { json });
    }
    throw err;
  }
}
