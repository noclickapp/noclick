/**
 * The `noclick` command (`npx noclick`): the same commands as the Python CLI's (`pip install noclick`), run from the
 * same spec. A curated command (the manifest's) runs what `register` was given for it; every `/v1` operation is a
 * command of its own; `api`, `describe` and `help` are built in.
 *
 * The key comes from `NOCLICK_API_KEY` when it's set, else from what `noclick login` stored for the profile in a
 * file (`--profile` or `NOCLICK_PROFILE`; the config directory `NOCLICK_CONFIG_DIR`, else `~/.config/noclick`).
 */

import { configure } from "../client.ts";
import { NoClickError } from "../errors.ts";
import { asUser } from "../scope.ts";
import { VERSION } from "../version.ts";
import { type ArgSpec, type FlagSpec, type Values, UsageError, helpText, parse } from "./args.ts";
import { commandsFor, runApi, runDescribe, runHelp, runOperation } from "./commands.ts";
import * as output from "./output.ts";
import type { Io } from "./output.ts";
import { host } from "./host.ts";
import { RUNNERS } from "./runners/index.ts";
import { type Command, load } from "./spec.ts";
import { PROFILE_ENV, signedIn } from "./store.ts";

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

function topHelp(io: Io): number {
  io.out(`usage: noclick <command> [flags]   (noclick ${VERSION})\n`);
  return runHelp(io, {});
}

/** Run the `noclick` command; returns its exit status. */
export async function main(
  argv: string[], io: Io = output.processIo, options: { signIn?: (profile: string) => void } = {},
): Promise<number> {
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
    if (flag === "-h" || flag === "--help") return topHelp(io);
    if (flag === "--profile") profile = rest.shift() ?? profile;
    else if (flag.startsWith("--profile=")) profile = flag.slice(10);
    else return output.report(io, new UsageError(`No global flag ${flag}.`, "noclick --help"), { json: false });
  }
  if (!rest.length) return topHelp(io);
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
        io.out(helpText(usage, command.summary, flags, args));
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
    if (spec.areas().has(area!)) {
      if (!name || name.startsWith("-")) return runHelp(io, { words: [area!] });
      throw new UsageError(`No command noclick ${area} ${name}.`, `noclick help ${area}`);
    }
    throw new UsageError(`No command noclick ${rest[0]}.`, "noclick help");
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
