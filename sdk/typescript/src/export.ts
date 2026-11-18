/** Exports: everything a user or an app holds, in formats that work elsewhere. */

import { asObject, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/**
 * One thing in an export and the form it leaves in: `kind` (`agent`, `conversations`, `memory`,
 * `database`, `files`, `dict`, `queue`, `code`, `app`, `credentials`, `phone_number`, `domain`),
 * its `name`, and `detail`, a sentence saying where it is in the zip and what to do with it.
 */
export interface ExportItem {
  kind: string;
  name: string;
  detail: string;
}

/**
 * What an export produced: a zip at `url` (a link that works until `expiresAt`, 7 days) of
 * `sizeBytes`, what's in it, and `remainingDependencies`, what keeps needing NoClick while the
 * account exists (`the agent runtime`, `channels`, `people's pending asks`, `app hosting`,
 * `connections`). The zip's `README.md` says the same for a person, its `manifest.json` for code.
 */
export interface ExportBundle {
  url: string | null;
  expiresAt: Date | null;
  sizeBytes: number;
  contents: ExportItem[];
  remainingDependencies: string[];
  raw: JsonObject;
}

/** @internal */
export function toExportBundle(result: unknown): ExportBundle {
  const raw = asObject(result);
  const items = Array.isArray(raw.contents) ? raw.contents : [];
  return {
    url: str(raw.url) ?? null,
    expiresAt: parseTime(raw.expires_at) ?? null,
    sizeBytes: typeof raw.size_bytes === "number" ? raw.size_bytes : 0,
    contents: items.map((i) => asObject(i)).map((i) => ({ kind: str(i.kind) ?? "", name: str(i.name) ?? "", detail: str(i.detail) ?? "" })),
    remainingDependencies: Array.isArray(raw.remaining_dependencies) ? raw.remaining_dependencies.filter((d): d is string => typeof d === "string") : [],
    raw,
  };
}
