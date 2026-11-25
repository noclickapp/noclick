/** Parsing a command line by the spec's own description of a command: its positional arguments and its flags. */

export interface FlagSpec {
  flag: string;
  dest: string;
  type: "bool" | "list" | "integer" | "number" | "string";
  short?: string;
  choices?: unknown[];
}

export interface ArgSpec {
  name: string;
  optional?: boolean;
  many?: boolean;
  choices?: unknown[];
}

export class UsageError extends Error {
  readonly type = "invalid_request";
  readonly nextStep: string | null;

  constructor(message: string, nextStep: string | null = null) {
    super(message);
    this.nextStep = nextStep;
  }
}

export type Values = Record<string, unknown>;

function convert(spec: FlagSpec, raw: string): unknown {
  if (spec.type === "integer" || spec.type === "number") {
    const value = Number(raw);
    if (!Number.isFinite(value) || (spec.type === "integer" && !Number.isInteger(value))) {
      throw new UsageError(`${spec.flag} takes ${spec.type === "integer" ? "a whole number" : "a number"}, not ${raw}.`);
    }
    return value;
  }
  if (spec.choices && spec.type !== "list" && !spec.choices.map(String).includes(raw)) {
    throw new UsageError(`${spec.flag} takes one of ${spec.choices.join(", ")}, not ${raw}.`);
  }
  return raw;
}

/** `argv` read by `flags` and `args`; `-h`/`--help` sets `help`. Unknown flags and missing arguments are usage
 *  errors naming the command. */
export function parse(argv: string[], flags: FlagSpec[], args: ArgSpec[], usage: string): Values {
  const values: Values = {};
  const byFlag = new Map<string, FlagSpec>();
  for (const spec of flags) {
    byFlag.set(spec.flag, spec);
    if (spec.short) byFlag.set(spec.short, spec);
  }
  const positionals: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i]!;
    if (token === "-h" || token === "--help") {
      values.help = true;
      continue;
    }
    if (token === "--") {
      positionals.push(...argv.slice(i + 1));
      break;
    }
    if (!token.startsWith("-") || token === "-") {
      positionals.push(token);
      continue;
    }
    const [name, inline] = token.includes("=") ? [token.slice(0, token.indexOf("=")), token.slice(token.indexOf("=") + 1)] : [token, undefined];
    let spec = byFlag.get(name);
    if (!spec && name.startsWith("--no-")) {
      const positive = byFlag.get(`--${name.slice(5)}`);
      if (positive?.type === "bool") {
        values[positive.dest] = false;
        continue;
      }
    }
    if (!spec) throw new UsageError(`${usage}: no flag ${name}.`, `${usage} --help`);
    if (spec.type === "bool") {
      values[spec.dest] = true;
      continue;
    }
    const raw = inline ?? argv[++i];
    if (raw === undefined) throw new UsageError(`${spec.flag} takes a value.`, `${usage} --help`);
    const value = convert(spec, raw);
    if (spec.type === "list") values[spec.dest] = [...((values[spec.dest] as unknown[]) ?? []), value];
    else values[spec.dest] = value;
  }
  if (values.help) return values;
  for (const spec of args) {
    if (spec.many) {
      if (!positionals.length && !spec.optional) throw new UsageError(`${usage} needs ${spec.name}.`, `${usage} --help`);
      values[spec.name] = positionals.splice(0);
      continue;
    }
    const value = positionals.shift();
    if (value === undefined) {
      if (spec.optional) continue;
      throw new UsageError(`${usage} needs ${spec.name}.`, `${usage} --help`);
    }
    if (spec.choices && !spec.choices.map((c) => String(c).toLowerCase()).includes(value.toLowerCase())) {
      throw new UsageError(`${spec.name} is one of ${spec.choices.join(", ")}, not ${value}.`, `${usage} --help`);
    }
    values[spec.name] = value;
  }
  if (positionals.length) throw new UsageError(`${usage}: unexpected ${positionals.join(" ")}.`, `${usage} --help`);
  return values;
}

/** A command's help, from the same specs it's parsed by. */
export function helpText(usage: string, summary: string, flags: (FlagSpec & { help?: string })[], args: (ArgSpec & { help?: string })[]): string {
  const lines = [`usage: ${usage}${args.map((a) => ` ${a.optional ? `[${a.name}]` : `<${a.name}>`}${a.many ? "..." : ""}`).join("")} [flags]`, "", summary];
  if (args.length) lines.push("", "arguments:", ...args.map((a) => `  ${a.name.padEnd(24)} ${a.help ?? ""}`));
  if (flags.length) lines.push("", "flags:", ...flags.map((f) => `  ${`${f.flag}${f.type === "bool" ? "" : ` <${f.type}>`}`.padEnd(24)} ${f.help ?? ""}`));
  return lines.join("\n");
}
