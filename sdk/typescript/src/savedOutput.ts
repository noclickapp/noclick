/**
 * SavedOutput: a step's output a person saved under a name while building, to show again or pin as the step's output.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asList, asObject, compact, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/**
 * An output saved under a name, kept by step type: read beside every step of that type on any workflow your account
 * opens, your account's own first (`mine`), then those made public or shared with it. Reading them takes what opening
 * the workflow takes; saving, renaming and deleting take what changing it takes, and renaming or deleting one also
 * takes being its owner or holding a share that may edit it. A key held to one of your users rejects with
 * `PermissionDenied`.
 */
export class SavedOutput {
  readonly id: string;
  readonly name: string;
  /** The type of step it was saved from. */
  readonly stepType: string;
  readonly output: JsonObject;
  /** `user` (your account's own, and whoever it's shared with) or `public` (anyone's to read). */
  readonly visibility: "user" | "public";
  readonly ownerId: string | null;
  /** Whether your account saved it. */
  readonly mine: boolean;
  readonly createdAt: Date | null;
  readonly updatedAt: Date | null;
  readonly raw: JsonObject;
  /** The workflow it was read on, which changing it goes through. */
  readonly workflowId: string;

  private constructor(workflowId: string, raw: JsonObject) {
    this.workflowId = workflowId;
    this.id = String(raw.id);
    this.name = String(raw.name ?? "");
    this.stepType = String(raw.step_type ?? "");
    this.output = asObject(raw.output);
    this.visibility = raw.visibility === "public" ? "public" : "user";
    this.ownerId = str(raw.owner_id);
    this.mine = raw.mine === true;
    this.createdAt = parseTime(raw.created_at);
    this.updatedAt = parseTime(raw.updated_at);
    this.raw = raw;
  }

  /**
   * The outputs saved for steps of `stepType`, read on the workflow `workflowId`: your account's own first, newest
   * first, then those made public or shared with it.
   *
   *     for (const saved of await SavedOutput.list(workflowId, "automation-shopify")) console.log(saved.name);
   */
  static async list(workflowId: string, stepType: string, options: { client?: NoClick } = {}): Promise<SavedOutput[]> {
    const raw = await resolveClient(options.client).request("GET", `/v1/workflows/${encodeURIComponent(workflowId)}/saved_outputs`, {
      query: { step_type: stepType },
      user: null,
    });
    return asList(raw).map((row) => new SavedOutput(workflowId, asObject(row)));
  }

  /**
   * Save an output of a step of the workflow `workflowId` under a name. Rejects with `PlanRequired` once the step type
   * keeps as many as your plan allows.
   *
   *     await SavedOutput.create(workflowId, { stepType: "automation-shopify", name: "A paid order", output });
   */
  static async create(
    workflowId: string,
    fields: { stepType: string; name: string; output: JsonObject; visibility?: "user" | "public" },
    options: { client?: NoClick } = {}
  ): Promise<SavedOutput> {
    const raw = await resolveClient(options.client).request("POST", `/v1/workflows/${encodeURIComponent(workflowId)}/saved_outputs`, {
      json: compact({ step_type: fields.stepType, name: fields.name, output: fields.output, visibility: fields.visibility }),
      user: null,
    });
    return new SavedOutput(workflowId, asObject(raw));
  }

  /** Rename it, or make it public or your account's own again. Resolves to it as it stands after. */
  async update(fields: { name?: string; visibility?: "user" | "public" }, options: { client?: NoClick } = {}): Promise<SavedOutput> {
    const raw = await resolveClient(options.client).request("PATCH", this.path(), { json: compact(fields), user: null });
    return new SavedOutput(this.workflowId, asObject(raw));
  }

  /** Delete it, with its shares. */
  async delete(options: { client?: NoClick } = {}): Promise<void> {
    await resolveClient(options.client).request("DELETE", this.path(), { user: null });
  }

  private path(): string {
    return `/v1/workflows/${encodeURIComponent(this.workflowId)}/saved_outputs/${encodeURIComponent(this.id)}`;
  }
}
