/**
 * The folder's linked app: `.noclick/project.json` at the folder's root, naming the app by name and id and the API
 * it's on, so a command run anywhere in the folder needs no app named. Never a key. The same file the Python CLI
 * reads and writes (`noclick/_cli/link.py`).
 */

import { withRun } from "./output.ts";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmdirSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import { NoClickError } from "../errors.ts";

export const FOLDER = ".noclick";
export const FILE = "project.json";

/** A command that needs an app ran where none is named or linked. Exits 2. */
export class NotLinked extends NoClickError {
  static override errorType = "not_linked";
}

export interface Link {
  app: string;
  appId: string | null;
  apiUrl: string | null;
  path: string;
}

/** The link of `start` (default: here) or the nearest folder above it holding one. */
export function find(start: string = process.cwd()): Link | null {
  let folder = resolve(start);
  for (;;) {
    const path = join(folder, FOLDER, FILE);
    if (existsSync(path)) {
      const data = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
      return {
        app: String(data.app), appId: (data.app_id as string | null) ?? null,
        apiUrl: (data.api_url as string | null) ?? null, path,
      };
    }
    const up = dirname(folder);
    if (up === folder) return null;
    folder = up;
  }
}

/** Link `root` (default: here) to `app`; a `.noclick/.gitignore` keeps it out of commits, since it's this machine's. */
export function write(app: string, options: { appId?: string | null; apiUrl?: string | null; root?: string } = {}): Link {
  const folder = join(options.root ?? process.cwd(), FOLDER);
  mkdirSync(folder, { recursive: true });
  writeFileSync(join(folder, ".gitignore"), "*\n");
  const path = join(folder, FILE);
  const saved = { app, app_id: options.appId ?? null, api_url: options.apiUrl ?? null };
  writeFileSync(path, `${JSON.stringify(saved, null, 2)}\n`);
  return { app, appId: saved.app_id, apiUrl: saved.api_url, path };
}

/** Forget the link `find` reads; the link it was, or null for none. The folder goes once nothing else is in it. */
export function remove(start?: string): Link | null {
  const found = find(start);
  if (found) {
    unlinkSync(found.path);
    const folder = dirname(found.path);
    const left = readdirSync(folder);
    if (left.every((name) => name === ".gitignore")) {
      for (const name of left) unlinkSync(join(folder, name));
      rmdirSync(folder);
    }
  }
  return found;
}

/** The app a command acts on: the one it names, else the folder's linked one. */
export function appName(named: string | null | undefined, start?: string): string {
  if (named) return named;
  const found = find(start);
  if (found) return found.app;
  throw withRun(new NotLinked("Name the app: this folder isn't linked to one.", {
    nextStep: "Pass the app's name, or link this folder once: noclick link <app>",
  }), ["noclick link <app>"]);
}
