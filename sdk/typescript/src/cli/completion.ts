/**
 * Shell completion, read from the spec as it is when Tab is pressed, so it follows every command the CLI has: the
 * Python CLI's `noclick/_cli/completion.py`, answering the same way, so one installed script works with either.
 *
 * `noclick completion <shell>` prints a short script that asks `noclick __complete -- <words>` what the word under the
 * cursor completes to: the commands at that point (curated ones and every API operation), a command's flags, a flag's
 * choices, a profile's name, and an app's name from a short-lived cache in the config directory (a stale one is read
 * again by a process of its own, never on the Tab that found it stale). Each answer is a line, `value<TAB>what it is`.
 */

import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

import { configure } from "../client.ts";
import { Project } from "../project.ts";
import { flagOf } from "./commands.ts";
import { host } from "./host.ts";
import type { Io } from "./output.ts";
import { type Command, type Flag, type Op, type Spec, load } from "./spec.ts";
import { activeProfile, configDir, readProfiles, resolveCredentials } from "./store.ts";

export const COMMAND = "__complete";
export const SHELLS = ["bash", "zsh", "fish", "powershell"] as const;
export type Shell = (typeof SHELLS)[number];
/** What a line naming it in a shell's startup file ends with, so --install adds it once. */
export const MARK = "# noclick completion";
export const APPS_FRESH_S = 300;
const APP_NAMES = ["app", "project"];
/** The commands whose argument names a profile. */
const PROFILE_ARGS = ["profile use", "profile show"];
type FlagLike = Pick<Flag, "flag" | "type" | "help" | "choices" | "short"> & { dest?: string };
const OP_FLAGS: FlagLike[] = [
  { flag: "--json", type: "bool", help: "Print the whole answer as JSON." },
  { flag: "--user", type: "string", help: "Act for this user: your id for them." },
  { flag: "--data", type: "string", help: "The whole request body: JSON, @file or - for stdin." },
  { flag: "--no-wait", type: "bool", help: "When it starts an operation, print its id instead of waiting." },
  { flag: "--timeout", type: "number", help: "Stop waiting after this many seconds." },
];
const HELP_FLAG: FlagLike = { flag: "--help", type: "bool", help: "Show this help." };

export type Candidate = [string, string];

/** A summary's first sentence, at most 70 characters. */
export function short(text: string | undefined): string {
  const first = (text ?? "").split("\n")[0]!.split(". ")[0]!.replace(/\.+$/, "");
  return first.length <= 70 ? first : `${first.slice(0, 69)}…`;
}

function opFlags(op: Op): FlagLike[] {
  const kinds: Record<string, Flag["type"]> = { boolean: "bool", list: "list", integer: "integer", number: "number" };
  const own = op.params.filter((p) => p.in !== "path").map((p): FlagLike => ({
    flag: flagOf(p.name), type: kinds[p.type] ?? "string", help: p.description ?? "",
    ...(p.choices?.length && !["boolean", "list", "json"].includes(p.type) ? { choices: p.choices } : {}),
  }));
  return [...own, ...OP_FLAGS];
}

const same = (a: string[], b: string[]) => a.length === b.length && a.every((w, i) => w === b[i]);

/** A command line read up to the word under the cursor: the command it names, how many positional words it has,
 *  and the flag waiting for a value. */
class Line {
  path: string[] = [];
  command: Command | null = null;
  op: Op | null = null;
  positional = 0;
  expecting: FlagLike | null = null;
  private readonly spec: Spec;
  private readonly areas: Map<string, Op[]>;

  constructor(spec: Spec, before: string[]) {
    this.spec = spec;
    this.areas = spec.areas();
    for (const word of before) {
      if (this.expecting) this.expecting = null;
      else if (word.startsWith("-")) {
        const flag = word.includes("=") ? null : this.flag(word);
        this.expecting = flag && flag.type !== "bool" ? flag : null;
      } else if (!this.command && !this.op && this.isNode([...this.path, word])) {
        this.path.push(word);
        this.command = spec.commands.find((c) => same(c.path, this.path)) ?? null;
        if (!this.command && this.path.length === 2) this.op = spec.find(this.path[0]!, this.path[1]!);
      } else this.positional += 1;
    }
  }

  private isNode(path: string[]): boolean {
    if (this.spec.commands.some((c) => same(c.path.slice(0, path.length), path))) return true;
    return (path.length === 1 && this.areas.has(path[0]!)) || (path.length === 2 && this.spec.find(path[0]!, path[1]!) !== null);
  }

  flags(): FlagLike[] {
    const own = this.command?.flags?.length ? this.command.flags : this.op ? opFlags(this.op) : [];
    return [...own, ...this.spec.manifest.globals, HELP_FLAG];
  }

  flag(word: string): FlagLike | undefined {
    return this.flags().find((f) => word === f.flag || word === f.short);
  }

  children(): Candidate[] {
    const depth = this.path.length;
    const found = new Map<string, string>();
    const summaries = new Map(this.spec.manifest.screens.sections.flatMap((s) => s.commands));
    for (const c of this.spec.commands) {
      if (c.path.length > depth && same(c.path.slice(0, depth), this.path)) {
        const name = c.path[depth]!;
        if (!found.has(name)) found.set(name, c.path.length === depth + 1 ? c.summary : summaries.get(name) ?? "");
      }
    }
    if (depth === 0) {
      for (const [name, summary] of summaries) found.set(name, summary);
      for (const [area, ops] of this.areas) if (!found.has(area)) found.set(area, `${ops.length} API operations`);
    } else if (depth === 1 && this.areas.has(this.path[0]!)) {
      for (const op of this.areas.get(this.path[0]!)!) if (!found.has(op.command)) found.set(op.command, short(op.summary));
    }
    return [...found].map(([name, summary]) => [name, short(summary)]);
  }

  argument(): Command["args"][number] | null {
    const args = this.command?.args ?? [];
    if (this.positional < args.length) return args[this.positional]!;
    return args.length && args[args.length - 1]!.many ? args[args.length - 1]! : null;
  }
}

/** What the last of `words` (the one under the cursor, perhaps empty) completes to. */
export function candidates(words: string[], lists: { profiles: () => string[]; apps: () => string[] }): Candidate[] {
  const all = words.length ? words : [""];
  const current = all[all.length - 1]!;
  const line = new Line(load(), all.slice(0, -1));
  const named = (names: string[], what: string): Candidate[] => names.map((n) => [n, what]);
  let found: Candidate[];
  if (line.expecting) {
    const flag = line.expecting;
    if (flag.flag === "--profile") found = named(lists.profiles(), "profile");
    else if (APP_NAMES.includes(flag.dest ?? "") || flag.flag === "--app") found = named(lists.apps(), "app");
    else found = (flag.choices ?? []).map((c) => [String(c), ""]);
  } else if (current.startsWith("-")) {
    found = line.flags().map((f) => [f.flag, short(f.help)]);
  } else if (!line.command && !line.op) {
    found = line.positional ? [] : line.children(); // a word that names nothing: nothing follows it
  } else {
    const arg = line.argument();
    if (!arg) found = [];
    else if (PROFILE_ARGS.includes(line.path.join(" "))) found = named(lists.profiles(), "profile");
    else if (APP_NAMES.includes(arg.name)) found = named(lists.apps(), "app");
    else found = (arg.choices ?? []).map((c) => [String(c), ""]);
  }
  const seen = new Set<string>();
  return found.filter(([value]) => value.startsWith(current) && !seen.has(value) && seen.add(value));
}

// --- app names, kept a few minutes ---------------------------------------------------------------------------------

type Kept = { at?: number; names?: string[] };

const appsPath = () => join(configDir(host.env), "cache", "apps.json");

function readApps(): Record<string, Kept> {
  try {
    return JSON.parse(readFileSync(appsPath(), "utf8")) as Record<string, Kept>;
  } catch {
    return {};
  }
}

export function writeApps(profile: string, entry: Kept): void {
  mkdirSync(dirname(appsPath()), { recursive: true });
  writeFileSync(appsPath(), `${JSON.stringify({ ...readApps(), [profile]: entry })}\n`);
}

/** The profile's apps as last read; when that's older than a few minutes, a read is started for the next Tab. Times
 *  are kept in seconds, as the Python CLI keeps them in the same file. */
export function appNames(profile: string, now = Date.now() / 1000,
  refresh: (profile: string) => void = (p) => host.detached([process.argv[1]!, COMMAND, "--refresh-apps", p])): string[] {
  const kept = readApps()[profile] ?? {};
  if (now - (kept.at ?? 0) >= APPS_FRESH_S) {
    try {
      writeApps(profile, { ...kept, at: now }); // one read started per few minutes, whether or not it answers
    } catch {
      return kept.names ?? [];
    }
    refresh(profile);
  }
  return kept.names ?? [];
}

async function refreshApps(profile: string): Promise<number> {
  const creds = resolveCredentials(host.env, profile);
  let names: string[] = [];
  if (creds.key) {
    configure({ apiKey: creds.key, baseUrl: creds.apiUrl, fetch: host.fetch });
    try {
      names = (await Project.list({ limit: 200 })).map((p) => p.name).filter(Boolean).sort();
    } catch {
      return 0; // what can't be read now is read again later
    }
  }
  writeApps(profile, { at: Date.now() / 1000, names });
  return 0;
}

// --- the scripts ---------------------------------------------------------------------------------------------------

export const SCRIPTS: Record<Shell, string> = {
  bash: `# noclick completion for bash: each Tab asks noclick what the word completes to.
_noclick_complete() {
  local IFS=$'\\n' line out
  out=$(noclick __complete -- "\${COMP_WORDS[@]:1:COMP_CWORD}" 2>/dev/null) || return 0
  COMPREPLY=()
  for line in $out; do COMPREPLY+=("\${line%%$'\\t'*}"); done
}
complete -o default -F _noclick_complete noclick
`,
  zsh: `#compdef noclick
# noclick completion for zsh: each Tab asks noclick what the word completes to.
_noclick() {
  local -a lines described
  local line
  lines=("\${(@f)$(noclick __complete -- "\${(@)words[2,CURRENT]}" 2>/dev/null)}")
  if [[ -z "\${lines[1]}" ]]; then _files; return; fi
  for line in "\${lines[@]}"; do described+=("\${\${line%%$'\\t'*}//:/\\\\:}:\${line#*$'\\t'}"); done
  _describe 'noclick' described
}
if [[ "\${funcstack[1]}" == "_noclick" ]]; then
  _noclick "$@"
else
  (( $+functions[compdef] )) || { autoload -Uz compinit && compinit; }
  compdef _noclick noclick
fi
`,
  fish: `# noclick completion for fish: each Tab asks noclick what the word completes to.
function __noclick_complete
    set -l words (commandline -opc)
    set -e words[1]
    set -l current (commandline -ct)
    noclick __complete -- $words "$current" 2>/dev/null
end
complete -c noclick -f -a '(__noclick_complete)'
`,
  powershell: `# noclick completion for PowerShell: each Tab asks noclick what the word completes to.
Register-ArgumentCompleter -Native -CommandName noclick -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    $words = @($commandAst.CommandElements | Select-Object -Skip 1 | ForEach-Object { $_.ToString() })
    $space = @()
    if ($wordToComplete -eq '') { $space = @('--space') }
    noclick __complete @space -- @words 2>$null | ForEach-Object {
        $value, $what = $_ -split "\`t", 2
        if (-not $what) { $what = $value }
        [System.Management.Automation.CompletionResult]::new($value, $value, 'ParameterValue', $what)
    }
}
`,
};

const home = () => host.env.HOME || homedir();
const dataDir = () => join(host.env.XDG_DATA_HOME || join(home(), ".local", "share"), "noclick");

/** Where --install writes the script, the startup file that loads it (null where the shell loads it by itself) and
 *  the line it adds there. */
export function places(shell: Shell): { script: string; rc: string | null; line: string | null } {
  const config = host.env.XDG_CONFIG_HOME || join(home(), ".config");
  if (shell === "fish") return { script: join(config, "fish", "completions", "noclick.fish"), rc: null, line: null };
  const script = join(dataDir(), `completion.${{ bash: "bash", zsh: "zsh", powershell: "ps1" }[shell]}`);
  if (shell === "powershell") {
    const rc = join(process.platform === "win32" ? join(home(), "Documents", "PowerShell") : join(config, "powershell"),
      "Microsoft.PowerShell_profile.ps1");
    return { script, rc, line: `if (Test-Path "${script}") { . "${script}" }  ${MARK}` };
  }
  const rc = shell === "zsh" ? join(host.env.ZDOTDIR || home(), ".zshrc") : join(home(), ".bashrc");
  return { script, rc, line: `[ -f "${script}" ] && . "${script}"  ${MARK}` };
}

/** Put the script in place and have the shell load it; what it says, each line. Run again, it changes nothing but
 *  the script, which it writes as this version has it. */
export function install(shell: Shell): string[] {
  const { script, rc, line } = places(shell);
  mkdirSync(dirname(script), { recursive: true });
  writeFileSync(script, SCRIPTS[shell]);
  const said = [`Installed noclick completion for ${shell}: ${script}`];
  if (!rc || !line) return [...said, "fish loads it by itself."];
  const held = existsSync(rc) ? readFileSync(rc, "utf8") : "";
  if (held.includes(MARK)) return [...said, `${rc} already loads it.`];
  mkdirSync(dirname(rc), { recursive: true });
  appendFileSync(rc, `${!held || held.endsWith("\n") ? "" : "\n"}${line}\n`);
  return [...said, `${rc} loads it (added a line).`];
}

// --- the hidden command a script calls -----------------------------------------------------------------------------

/** `noclick __complete [--space] -- <words>`: one `value<TAB>what` line per candidate. `--space` says the cursor is
 *  past the last word (PowerShell can't pass an empty word); `--refresh-apps <profile>` reads the profile's apps into
 *  the cache. */
export async function answer(argv: string[], io: Io): Promise<number> {
  if (argv[0] === "--refresh-apps") return await refreshApps(argv[1] ?? "default");
  const dash = argv.indexOf("--");
  const space = (dash < 0 ? argv : argv.slice(0, dash)).includes("--space");
  const words = dash < 0 ? argv.filter((w) => w !== "--space") : argv.slice(dash + 1);
  if (space) words.push("");
  const at = words.slice(0, -1).indexOf("--profile");
  const flagged = words.find((w) => w.startsWith("--profile="))?.slice(10) ?? (at >= 0 ? words[at + 1] : undefined);
  const [profile] = activeProfile(host.env, flagged || undefined);
  try {
    const found = candidates(words, {
      profiles: () => Object.keys(readProfiles(host.env)).sort(),
      apps: () => appNames(profile),
    });
    for (const [value, what] of found) io.out(`${value}\t${what}`);
  } catch {
    // a Tab that can't be answered completes to nothing, never a stack trace
  }
  return 0;
}
