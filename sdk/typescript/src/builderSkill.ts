/**
 * BuilderSkill: the skills NoClick's workflow builder loads before it builds, apart from the Agent Skills an agent
 * attaches (`Skill`).
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asList, asObject, compact, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** What a builder skill says, set when it's made or changed. */
export interface BuilderSkillFields {
  name?: string;
  /** When the builder should use it: what it reads to decide. */
  description?: string;
  /** What it tells the builder; an empty string clears it. */
  bodyText?: string;
  /** A workflow it may follow (nodes and edges). */
  bodyWorkflow?: JsonObject;
  /** Whether the builder loads it. */
  enabled?: boolean;
}

/** What a skill's workflow is saved with besides itself (`saveWorkflow`). */
export interface SkillWorkflowSave {
  /** The `workflowVersion` it was read at: a save on one the workflow has moved past rejects with `Conflict`, whose
   *  `details` hold the `workflow` and `version` as they stand. Left out, it's written as it is. */
  ifVersion?: number | null;
  /** The canvas's viewport and the like. */
  displayMetadata?: JsonObject | null;
  /** Steps removed since the version read. */
  deletedSteps?: string[];
  /** Steps held only in part: their settings are kept as stored. */
  partialSteps?: string[];
  /** What changed since `ifVersion` (a closing page's last save, which reads no answer): on a workflow that moved
   *  past it, only these land, on it as it stands. */
  changes?: { steps?: string[]; edgesAdded?: string[]; edgesRemoved?: string[] };
  /** In a browser, send the save so it outlives the page (a closing tab's last save; `RequestOptions.keepalive`). */
  keepalive?: boolean;
}

/** A saved workflow: the version it's at now, and whether the save changed it. */
export interface SkillWorkflowSaved {
  version: number;
  changed: boolean;
}

/**
 * A skill NoClick's builder loads: a description the builder reads to decide whether it needs it, plus text and,
 * optionally, a workflow to follow. `scope` says whose: `owned` (your account's, or a workspace it's in) or `shared`
 * (shared with it to read). It loads while it's `enabled` and not `muted` for your account. They're what Settings →
 * Skills in the NoClick app shows. Any of your account's own keys reads and changes them; one held to one of your users
 * rejects with `PermissionDenied`.
 */
export class BuilderSkill {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly scope: "owned" | "shared";
  readonly ownerId: string | null;
  readonly enabled: boolean;
  /** Muted for your account alone: the way to stop one shared with it loading. */
  readonly muted: boolean;
  readonly hasText: boolean;
  readonly hasWorkflow: boolean;
  /** Its text and workflow, on one read whole (`get`, and what a change answers); null on a list's. */
  readonly bodyText: string | null;
  readonly bodyWorkflow: JsonObject | null;
  /** The version its workflow is at, which `saveWorkflow` saves on (a read whole); null on a list's. */
  readonly workflowVersion: number | null;
  /** The app canvas's viewport over its workflow (a read whole); null on a list's. */
  readonly displayMetadata: JsonObject | null;
  readonly createdAt: Date | null;
  readonly updatedAt: Date | null;
  readonly raw: JsonObject;

  private constructor(raw: JsonObject) {
    this.id = String(raw.id);
    this.name = String(raw.name ?? "");
    this.description = str(raw.description) ?? "";
    this.scope = raw.scope === "shared" ? "shared" : "owned";
    this.ownerId = str(raw.owner_id);
    this.enabled = raw.enabled === true;
    this.muted = raw.muted === true;
    this.hasText = raw.has_text === true;
    this.hasWorkflow = raw.has_workflow === true;
    this.bodyText = str(raw.body_text);
    this.bodyWorkflow = raw.body_workflow && typeof raw.body_workflow === "object" ? asObject(raw.body_workflow) : null;
    this.workflowVersion = typeof raw.workflow_version === "number" ? raw.workflow_version : null;
    this.displayMetadata = raw.display_metadata && typeof raw.display_metadata === "object" ? asObject(raw.display_metadata) : null;
    this.createdAt = parseTime(raw.created_at);
    this.updatedAt = parseTime(raw.updated_at);
    this.raw = raw;
  }

  /**
   * Your account's builder skills (`owned`), newest first, then those shared with it (`shared`).
   *
   *     for (const skill of await BuilderSkill.list()) console.log(skill.name, skill.enabled && !skill.muted);
   */
  static async list(options: { client?: NoClick } = {}): Promise<BuilderSkill[]> {
    const raw = await resolveClient(options.client).request("GET", "/v1/builder_skills", { user: null });
    return asList(raw).map((row) => new BuilderSkill(asObject(row)));
  }

  /**
   * Make a builder skill in your account's active workspace.
   *
   *     await BuilderSkill.create({ name: "Brand voice", description: "How we write.", bodyText: "Short sentences." });
   */
  static async create(fields: BuilderSkillFields & { name: string }, options: { client?: NoClick } = {}): Promise<BuilderSkill> {
    const raw = await resolveClient(options.client).request("POST", "/v1/builder_skills", { json: wire(fields), user: null });
    return new BuilderSkill(asObject(raw));
  }

  /** One builder skill, with its text and workflow. */
  static async get(id: string, options: { client?: NoClick } = {}): Promise<BuilderSkill> {
    const raw = await resolveClient(options.client).request("GET", `/v1/builder_skills/${encodeURIComponent(id)}`, { user: null });
    return new BuilderSkill(asObject(raw));
  }

  /**
   * Change it: what it says or whether it's enabled (its owner, or a share that may edit it; others reject with
   * `PermissionDenied`), and whether it's `muted` for your account (anyone it reaches). Fields left out stay as they
   * are. Resolves to it as it stands after.
   *
   *     await skill.update({ muted: true });
   */
  async update(fields: BuilderSkillFields & { muted?: boolean }, options: { client?: NoClick } = {}): Promise<BuilderSkill> {
    const raw = await resolveClient(options.client).request("PATCH", `/v1/builder_skills/${encodeURIComponent(this.id)}`, {
      json: { ...wire(fields), ...compact({ muted: fields.muted }) },
      user: null,
    });
    return new BuilderSkill(asObject(raw));
  }

  /**
   * Save a skill's workflow whole, as NoClick's canvas does (its owner, or a share that may edit it), on the version
   * it was read at. Resolves to the version it's at after; a save of the workflow as stored changes nothing.
   *
   *     const skill = await BuilderSkill.get(id);
   *     await BuilderSkill.saveWorkflow(skill.id, { nodes, edges }, { ifVersion: skill.workflowVersion });
   */
  static async saveWorkflow(id: string, workflow: JsonObject, save: SkillWorkflowSave = {}, options: { client?: NoClick } = {}): Promise<SkillWorkflowSaved> {
    const changes = save.changes
      ? { steps: save.changes.steps ?? [], edges_added: save.changes.edgesAdded ?? [], edges_removed: save.changes.edgesRemoved ?? [] }
      : undefined;
    const raw = asObject(
      await resolveClient(options.client).request("PUT", `/v1/builder_skills/${encodeURIComponent(id)}/workflow`, {
        json: compact({
          workflow,
          if_version: save.ifVersion ?? undefined,
          display_metadata: save.displayMetadata ?? undefined,
          deleted_steps: save.deletedSteps?.length ? save.deletedSteps : undefined,
          partial_steps: save.partialSteps?.length ? save.partialSteps : undefined,
          changes,
        }),
        user: null,
        keepalive: save.keepalive,
      })
    );
    return { version: Number(raw.version), changed: raw.changed === true };
  }

  /** Delete it for good: only the account that made it may. */
  async delete(options: { client?: NoClick } = {}): Promise<void> {
    await resolveClient(options.client).request("DELETE", `/v1/builder_skills/${encodeURIComponent(this.id)}`, { user: null });
  }
}

function wire(fields: BuilderSkillFields): JsonObject {
  return compact({
    name: fields.name,
    description: fields.description,
    body_text: fields.bodyText,
    body_workflow: fields.bodyWorkflow,
    enabled: fields.enabled,
  });
}
