/**
 * Reading and editing a Worker's wrangler config as written, as the Python CLI's `noclick/_cli/appconfig.py` does:
 * JSONC read with its comments and trailing commas left out, and one top-level key set with everything else (its
 * comments, its order) kept.
 */

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { jsonText } from "./output.ts";

export const WRANGLER_FILES = ["wrangler.jsonc", "wrangler.json", "wrangler.toml"];

/** JSONC as JSON: comments and trailing commas out, strings untouched. */
export function stripJsonc(text: string): string {
  let out = "";
  let i = 0;
  const n = text.length;
  while (i < n) {
    const c = text[i]!;
    if (c === '"') {
      let j = i + 1;
      while (j < n && text[j] !== '"') j += text[j] === "\\" ? 2 : 1;
      out += text.slice(i, j + 1);
      i = j + 1;
    } else if (text.startsWith("//", i)) {
      while (i < n && text[i] !== "\n") i += 1;
    } else if (text.startsWith("/*", i)) {
      const end = text.indexOf("*/", i + 2);
      i = end < 0 ? n : end + 2;
    } else {
      out += c;
      i += 1;
    }
  }
  return out.replace(/,(\s*[}\]])/g, "$1");
}

export function findWrangler(folder: string): string | null {
  for (const name of WRANGLER_FILES) if (existsSync(join(folder, name))) return join(folder, name);
  return null;
}

/** A JSON or JSONC wrangler config, as an object (a TOML one is never read here). */
export function readWrangler(path: string): Record<string, unknown> {
  const name = path.split(/[\\/]/).pop()!;
  let data: unknown;
  try {
    data = JSON.parse(stripJsonc(readFileSync(path, "utf8").replace(/^\uFEFF/, "")));
  } catch (err) {
    throw Object.assign(new Error(`${name} isn't valid JSON (${(err as Error).message}).`), { nextStep: `Fix ${name}, then deploy again.` });
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw Object.assign(new Error(`${name} is a JSON object, not ${Array.isArray(data) ? "list" : typeof data}.`), { nextStep: `Fix ${name}, then deploy again.` });
  }
  return data as Record<string, unknown>;
}

/** Past whitespace and comments from `i`. */
function skip(text: string, i: number): number {
  while (i < text.length) {
    if (/\s/.test(text[i]!)) i += 1;
    else if (text.startsWith("//", i)) {
      const end = text.indexOf("\n", i);
      i = end < 0 ? text.length : end;
    } else if (text.startsWith("/*", i)) {
      const end = text.indexOf("*/", i + 2);
      i = end < 0 ? text.length : end + 2;
    } else break;
  }
  return i;
}

function stringEnd(text: string, i: number): number {
  let j = i + 1;
  while (j < text.length && text[j] !== '"') j += text[j] === "\\" ? 2 : 1;
  return j + 1;
}

/** Where the JSON value starting at `i` ends. */
function valueEnd(text: string, i: number): number {
  if (text[i] === '"') return stringEnd(text, i);
  if (text[i] === "{" || text[i] === "[") {
    let depth = 0;
    let j = i;
    while (j < text.length) {
      j = skip(text, j);
      const c = text[j];
      if (c === '"') {
        j = stringEnd(text, j);
        continue;
      }
      if (c === "{" || c === "[") depth += 1;
      else if (c === "}" || c === "]") {
        depth -= 1;
        if (depth === 0) return j + 1;
      }
      j += 1;
    }
    throw new Error("unbalanced");
  }
  let j = i;
  while (j < text.length && !",}] \t\r\n/".includes(text[j]!)) j += 1;
  return j;
}

/** Each top-level key's value span, and the root's closing brace (`"}"`). */
function topLevel(text: string): Map<string, [number, number]> {
  let i = skip(text, 0);
  if (i >= text.length || text[i] !== "{") throw new Error("not an object");
  const spans = new Map<string, [number, number]>();
  i = skip(text, i + 1);
  while (i < text.length && text[i] !== "}") {
    const end = stringEnd(text, i);
    const key = JSON.parse(text.slice(i, end)) as string;
    i = skip(text, end);
    i = skip(text, i + 1); // past ':'
    const after = valueEnd(text, i);
    spans.set(key, [i, after]);
    i = skip(text, after);
    if (i < text.length && text[i] === ",") i = skip(text, i + 1);
  }
  spans.set("}", [i, i + 1]);
  return spans;
}

/** The last character before `before` that isn't whitespace or a comment. */
function lastCode(text: string, before: number): string {
  let i = skip(text, 0);
  let last = "";
  while (i < before) {
    if (text[i] === '"') {
      i = stringEnd(text, i);
      last = '"';
    } else {
      last = text[i]!;
      i += 1;
    }
    i = skip(text, i);
  }
  return last;
}

function endOfValue(text: string, before: number): number {
  let i = skip(text, 0);
  let end = 0;
  while (i < before) {
    i = text[i] === '"' ? stringEnd(text, i) : i + 1;
    end = i;
    i = skip(text, i);
  }
  return end;
}

function indentOf(text: string): string {
  return /\n([ \t]+)"/.exec(text)?.[1] ?? "  ";
}

/** `text` (JSON or JSONC) with its top-level `key` set to `value`, comments and everything else as written. */
export function setTopLevel(text: string, key: string, value: unknown): string {
  const spans = topLevel(text);
  const indent = indentOf(text);
  const rendered = jsonText(value, indent.replace(/\t/g, "  ").length || 2).replaceAll("\n", `\n${indent}`);
  const held = spans.get(key);
  if (held) return text.slice(0, held[0]) + rendered + text.slice(held[1]);
  let close = spans.get("}")![0];
  if (!["{", ","].includes(lastCode(text, close))) {
    const end = endOfValue(text, close);
    text = `${text.slice(0, end)},${text.slice(end)}`;
    close += 1;
  }
  const at = text.slice(0, close).trimEnd().length;
  return `${text.slice(0, at)}\n${indent}${JSON.stringify(key)}: ${rendered}\n${text.slice(close)}`;
}
