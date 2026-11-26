/**
 * A command's `--help` at a terminal, as a person reads it: a `Usage:` line, its description, then sections
 * (Arguments, Options, Notes, Examples) each under a heading and a rule, names in one column and what they do dimmed
 * beside them; the Python CLI's `noclick/_cli/helpscreen.py` draws the same. Off a terminal, the plain help is
 * printed as it always was.
 */

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
