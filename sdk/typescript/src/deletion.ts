/**
 * What a deletion would do, before it's made: `previewDelete` names a `DELETE` (or a closing `POST`) and says what goes
 * with it, what stops working, what data is lost, what stops billing and whether it can be taken back, with the
 * confirm token the call itself needs where the account's policy asks for one.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asList, asObject, num, str } from "./object.ts";
import type { JsonObject } from "./object.ts";
import type { UserOption } from "./scope.ts";

/** What a deletion does, in words a person reads before agreeing. */
export interface DeletionImpact {
  deletes: string;
  /** What has to go first, or stops working with it. */
  dependsOnIt: string[];
  dataLost: string[];
  stopsBilling: string[];
  /** Whether it can be taken back (`undo` says how). */
  reversible: boolean;
  undo: string | null;
}

/** A deletion previewed: its `operation`, `method` and `path`, what it's called (`title`), its `impact`, and the
 *  `confirmToken` (good for `expiresInS` seconds) the call takes. */
export interface DeletionPreview {
  operation: string;
  method: string;
  path: string;
  title: string | null;
  impact: DeletionImpact;
  confirmToken: string;
  expiresInS: number;
  raw: JsonObject;
}

/**
 * What `method path` would delete (`DELETE`, or `POST` for a cancel, close or clear), as the account sees it (`user`:
 * as one of its users does): what goes, what depends on it, what data is lost and whether it can be taken back.
 * `body` is the call's own, for a deletion judged by it (a workflow's edits that remove steps). Nothing is deleted.
 *
 *     const { impact } = await previewDelete("DELETE", `/v1/agents/${agent.id}`);
 *     console.log(impact.deletes, impact.reversible ? impact.undo : "for good");
 */
export async function previewDelete(
  method: "DELETE" | "POST", path: string, options: { body?: unknown; user?: UserOption; client?: NoClick } = {},
): Promise<DeletionPreview> {
  const raw = asObject(await resolveClient(options.client).request("POST", "/v1/delete_previews", {
    json: { method, path, ...(options.body !== undefined ? { body: options.body } : {}) },
    user: options.user,
  }));
  const impact = asObject(raw.impact);
  const texts = (value: unknown) => asList(value).map(String);
  return {
    operation: str(raw.operation) ?? "", method: str(raw.method) ?? method, path: str(raw.path) ?? path, title: str(raw.title),
    impact: {
      deletes: str(impact.deletes) ?? "", dependsOnIt: texts(impact.depends_on_it), dataLost: texts(impact.data_lost),
      stopsBilling: texts(impact.stops_billing), reversible: impact.reversible === true, undo: str(impact.undo),
    },
    confirmToken: str(raw.confirm_token) ?? "", expiresInS: num(raw.expires_in_s) ?? 0, raw,
  };
}
