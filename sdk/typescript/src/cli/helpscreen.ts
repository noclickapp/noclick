/**
 * A command's `--help` at a terminal, as a person reads it: a `Usage:` line, its description, then sections
 * (Arguments, Options, Notes, Examples) each under a heading and a rule, names in one column and what they do dimmed
 * beside them; the Python CLI's `noclick/_cli/helpscreen.py` draws the same. Off a terminal, the plain help is
 * printed as it always was.
 */

import type { Arg, Command, Flag } from "./spec.ts";
import type { Style } from "./style.ts";

const NAME_COLUMN = 28;

export function wrap(text: string, width: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    if (line && line.length + 1 + word.length > width) {
      lines.push(line);
      line = word;
    } else line = line ? `${line} ${word}` : word;
  }
  if (line) lines.push(line);
  return lines;
}

/** Names in one column and what they do beside them, dimmed, wrapped under its own column. */
export function rows(items: [string, string][], s: Style, width: number): string[] {
  if (!items.length) return [];
  const column = Math.min(Math.max(...items.map(([name]) => name.length)), NAME_COLUMN);
  const room = Math.max(width - column - 6, 30);
  const out: string[] = [];
  for (const [name, text] of items) {
    const lines = wrap(text, room);
    if (!lines.length) lines.push("");
    const pad = " ".repeat(column);
    if (name.length > column) {
      out.push(`  ${s.accent(name)}`, ...lines.map((l) => `  ${pad}  ${s.dim(l)}`));
      continue;
    }
    out.push(`  ${s.accent(name.padEnd(column))}  ${s.dim(lines[0]!)}`.trimEnd(), ...lines.slice(1).map((l) => `  ${pad}  ${s.dim(l)}`));
  }
  return out;
}

export interface HelpScreen {
  usage: string;
  description?: string;
  middle?: string[];
  sections: [string, [string, string][]][];
  notes?: string;
  examples?: string[];
}

export function screen(s: Style, help: HelpScreen): string {
  const width = Math.min(s.width(), 100);
  const lines = [`${s.bold("Usage:")} ${help.usage}`, ""];
  if (help.description) lines.push(...help.description.split("\n").flatMap((p) => (p ? wrap(p, width) : [""])), "");
  if (help.middle?.length) lines.push(...help.middle, "");
  for (const [title, items] of help.sections) if (items.length) lines.push(...s.section(title), ...rows(items, s, width), "");
  if (help.notes) lines.push(...s.section("Notes"), ...wrap(help.notes, width - 2).map((l) => `  ${s.dim(l)}`), "");
  if (help.examples?.length) lines.push(...s.section("Examples"), ...help.examples.map((e) => `  ${s.link(e)}`), "");
  return lines.join("\n").trimEnd();
}

/** A flag as its help names it: `-r, --recursive`, `--app APP`, `--env {all,production,preview}`, `--preview [NAME]`
 *  (its value may be left out), as the Python CLI's `helpscreen.invocation`. */
export function invocation(flag: Flag): string {
  const names = flag.short ? `${flag.short}, ${flag.flag}` : flag.flag;
  if (flag.type === "bool") return names;
  const value = flag.choices?.length ? `{${flag.choices.join(",")}}` : (flag.metavar ?? flag.dest.toUpperCase());
  return "const" in flag ? `${names} [${value}]` : `${names} ${value}`;
}

const argument = (arg: Arg) => {
  const name = arg.metavar ?? arg.name;
  return (arg.optional ? `[${name}]` : `<${name}>`) + (arg.many ? "..." : "");
};

/** `noclick secret set [OPTIONS] <name>`: a curated command's usage, from the manifest. */
export function usageOf(command: Command): string {
  return ["noclick", ...command.path, ...(command.flags.length ? ["[OPTIONS]"] : []), ...command.args.map(argument)].join(" ");
}

/** What every command's help lists after its own options: the flags any command takes. */
export function globalFlags(globals: Flag[]): [string, string][] {
  return [...globals.filter((g) => g.flag !== "--version").map((g) => [invocation(g), g.help ?? ""] as [string, string]), ["-h, --help", "Show this help."]];
}

/** A curated command's help, from the manifest: what the Python CLI's `helpscreen.command_screen` draws for it. */
export function commandScreen(command: Command, globals: Flag[], s: Style): string {
  return screen(s, {
    usage: usageOf(command), description: command.summary,
    sections: [
      ["Arguments", command.args.map((a) => [a.metavar ?? a.name, a.help ?? ""] as [string, string])],
      ["Options", command.flags.map((f) => [invocation(f), f.help ?? ""] as [string, string])],
      ["Global flags", globalFlags(globals)],
    ],
    notes: command.notes, examples: command.examples,
  });
}
