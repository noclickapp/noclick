/** Earlier values: what a secret or an app's setting held before it changed, kept 30 days. */

import { asList, asObject, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/**
 * A value a secret or setting held before `replacedAt`. `op` says what replaced it: `changed` (a new
 * value) or `deleted`. A secret's version never shows its value: `keys` names what a `Secret` held
 * and `environment` is where an app's secret was set; a setting's shows its `value`.
 */
export interface Version {
  id: string;
  name: string;
  op: "changed" | "deleted";
  replacedAt: Date | null;
  environment: string | null;
  keys: string[] | null;
  value: string | null;
  raw: JsonObject;
}

/** @internal */
export function toVersions(payload: unknown): Version[] {
  return (asList(payload) as unknown[]).map((row) => {
    const raw = asObject(row);
    return {
      id: str(raw.id) ?? "", name: str(raw.name) ?? "", op: raw.op as Version["op"],
      replacedAt: parseTime(raw.replaced_at), environment: str(raw.environment),
      keys: Array.isArray(raw.keys) ? raw.keys.map(String) : null, value: str(raw.value), raw,
    };
  });
}

/** @internal A `Version` or its id. */
export function versionId(version: Version | string): string {
  return encodeURIComponent(typeof version === "string" ? version : version.id);
}
