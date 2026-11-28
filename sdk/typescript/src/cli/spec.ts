/**
 * The `noclick` command surface as data, the same files the Python CLI runs from (`noclick/_cli/spec/` in the
 * Python package; this CLI's build bundles them): the curated commands (`manifest.json`, written by hand, each one's
 * arguments, flags and examples) and one command per `/v1` operation (`operations.json`, generated from the API's own
 * description).
 */

import manifestJson from "../../../python/noclick/_cli/spec/manifest.json" with { type: "json" };
import operationsJson from "../../../python/noclick/_cli/spec/operations.json" with { type: "json" };

export interface Param {
  name: string;
  in: "path" | "query" | "body";
  type: "string" | "integer" | "number" | "boolean" | "list" | "json";
  required?: boolean;
  secret?: boolean;
  choices?: (string | number)[];
  default?: unknown;
  description?: string;
  /** Where the names of what it names are listed: its list operation, what one and several of it are called, and
   *  the query narrowing the list to a name. */
  lookup?: { list: string; noun: string; plural: string; query?: string };
}

export interface Op {
  name: string;
  area: string;
  command: string;
  method: string;
  path: string;
  risk: string;
  summary: string;
  body: "merge" | "wrap" | null;
  params: Param[];
  /** Names its command had: they still run it, but no list shows them. */
  aliases?: string[];
}

export interface Flag {
  flag: string;
  dest: string;
  type: "bool" | "list" | "integer" | "number" | "string";
  short?: string;
  choices?: unknown[];
  required?: boolean;
  metavar?: string;
  help?: string;
  /** A flag whose value is optional: what it is given alone (`--preview` is `--preview ""`). */
  const?: string | null;
  /** What it is when not given. */
  default?: unknown;
}

export interface Arg {
  name: string;
  /** What its help calls it, where that isn't its name. */
  metavar?: string;
  optional?: boolean;
  many?: boolean;
  choices?: unknown[];
  help?: string;
}

export interface Command {
  path: string[];
  summary: string;
  auth: boolean;
  args: Arg[];
  flags: Flag[];
  one_of?: { dests: string[]; required: boolean }[];
  notes?: string;
  examples?: string[];
}

/** What the CLI shows before a command runs (`screens.ts`): its words, by section and row. */
export interface Screens {
  intro: string;
  sections: { name: string; commands: [string, string][] }[];
  areas: [string, string];
  first: [string, string][];
  next: [string, string][];
  signed_out: string;
  signup: { terms: [string, string]; harnesses: [string, string][]; works: string };
  /** `noclick resources`' kinds: each one's list route and its columns (header, field, how it's shown). */
  resources: ResourceKind[];
  /** Words that mean others: `top` as the command (`ls`), `group` under a group without one of its own. */
  aliases: {
    top: Record<string, string>;
    group: Record<string, string>;
    /** Older spellings, kept working and listed nowhere: the words, the command they now are, and what their leading
     *  arguments become (`--app`, `=`). */
    old: [string[], string[], string[]][];
    valued: string[];
  };
  /** An error's words as the command line says them (`said.ts`). */
  said: {
    /** By kind: the words before the command that makes one, and the command (`{name}` its name). */
    makes: Record<string, [string, string]>;
    made_by: Record<string, string>;
    kind_words: Record<string, string>;
    unreachable: [string, string][];
    default_api: string;
  };
}

export interface ResourceKind {
  kind: string;
  title: string;
  path: string;
  query?: Record<string, string>;
  columns: [string, string, "text" | "status" | "usd" | "bytes" | "bool" | "date"][];
}

export interface Manifest {
  format: number;
  globals: Flag[];
  commands: Command[];
  /** `noclick init`'s templates: what each is and its files (`{name}` is the app's name). */
  templates: Record<string, { about: string; files: Record<string, string> }>;
  screens: Screens;
}

export class Spec {
  readonly manifest: Manifest;
  readonly operations: Op[];
  readonly #byCommand = new Map<string, Op>();
  readonly #byName = new Map<string, Op>();

  constructor(manifest: Manifest, operations: { operations: Op[] }) {
    this.manifest = manifest;
    this.operations = operations.operations;
    for (const op of this.operations) {
      this.#byCommand.set(`${op.area} ${op.command}`, op);
      this.#byName.set(op.name, op);
    }
    for (const op of this.operations) {
      // A name a command had still runs it, never a command's own name.
      for (const alias of op.aliases ?? []) if (!this.#byCommand.has(`${op.area} ${alias}`)) this.#byCommand.set(`${op.area} ${alias}`, op);
    }
  }

  get commands(): Command[] {
    return this.manifest.commands;
  }

  areas(): Map<string, Op[]> {
    const found = new Map<string, Op[]>();
    for (const op of this.operations) {
      const list = found.get(op.area) ?? [];
      list.push(op);
      found.set(op.area, list);
    }
    return found;
  }

  /** An operation by its command, or a name its command had (a hidden alias). */
  find(area: string, command: string): Op | null {
    return this.#byCommand.get(`${area} ${command}`) ?? null;
  }

  named(name: string): Op | null {
    return this.#byName.get(name) ?? null;
  }

  curated(path: string[]): Command | null {
    return this.commands.find((c) => c.path.length === path.length && c.path.every((w, i) => w === path[i])) ?? null;
  }

  /** The operation a `METHOD /v1/...` call makes: its template, or a concrete path it matches. */
  forCall(method: string, path: string): Op | null {
    const verb = method.toUpperCase();
    const given = path.split("?")[0]!.replace(/^\/|\/$/g, "").split("/");
    let best: [number, Op] | null = null;
    for (const op of this.operations) {
      const template = op.path.replace(/^\/|\/$/g, "").split("/");
      if (op.method !== verb || template.length !== given.length) continue;
      let literal = 0;
      let matches = true;
      for (let i = 0; i < template.length; i++) {
        if (template[i]!.startsWith("{")) continue;
        if (template[i] !== given[i]) {
          matches = false;
          break;
        }
        literal++;
      }
      if (matches && (!best || literal > best[0])) best = [literal, op];
    }
    return best ? best[1] : null;
  }

  /** An operation by `<area> <command>`, its name, or `METHOD /v1/...`. */
  lookup(words: string[]): Op | null {
    if (words.length === 2 && ["GET", "POST", "PUT", "PATCH", "DELETE"].includes(words[0]!.toUpperCase())) {
      return this.forCall(words[0]!, words[1]!);
    }
    if (words.length === 2) return this.find(words[0]!, words[1]!);
    if (words.length === 1) return this.named(words[0]!.replace(/-/g, "_"));
    return null;
  }

  /** Whether a curated command has the operation's name (`domains search`), or its area's (`status`, a command of its
   *  own): that name runs the curated one. */
  shadowed(op: Op): boolean {
    return this.curated([op.area, op.command]) !== null || this.curated([op.area]) !== null;
  }
}

let loaded: Spec | null = null;

export function load(): Spec {
  loaded ??= new Spec(manifestJson as unknown as Manifest, operationsJson as { operations: Op[] });
  return loaded;
}
