/**
 * Sharing your resources with people, as the app's Share dialog does.
 *
 *     const intake = Workflow.fromName("Order intake");
 *     const share = await Share.create(intake, { email: "sam@example.com", access: "edit" });
 *     console.log((await Share.list(intake)).map((s) => [s.name, s.access]));
 *     await share.delete();
 *
 * A workflow, a workflow folder, a database, a connection, a saved output or a skill is shared with a person by email
 * (who's told, and gets it once they have an account), a team workspace of the NoClick app, or, for a workflow, anyone
 * with the link. Whoever manages the resource's shares (its owner, or a team workspace's admin for the workspace's own)
 * reads and changes them. Sharing is between people: a call acting for one of your users has none.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asObject, parseTime, refId } from "./object.ts";
import type { ApiObject, JsonObject } from "./object.ts";
import { Workflow } from "./workflow.ts";

/** What can be shared. */
export type SharedResourceType = "workflow" | "workflow_folder" | "database" | "credential" | "saved_output" | "skill";
/** What a share allows. */
export type ShareAccess = "view" | "edit";

/** A resource: a `Workflow`, or any resource's id with its `resourceType`. */
type Shared = string | ApiObject;

async function resource(shared: Shared, resourceType?: SharedResourceType): Promise<{ resource_type: string; resource_id: string }> {
  const kind = resourceType ?? (shared instanceof Workflow ? "workflow" : undefined);
  if (!kind) {
    throw new Error("Name the resourceType of anything but a Workflow: workflow, workflow_folder, database, credential, saved_output or skill.");
  }
  return { resource_type: kind, resource_id: String(await refId(shared)) };
}

/** A personal workflow's invite link: whoever opens it signed in joins the workflow with its `access`. */
export interface ShareInviteLink {
  workflowId: string;
  url: string;
  token: string;
  access: ShareAccess;
}

/** Who one of your resources is shared with, and what they may do with it. */
export class Share {
  readonly id: string;
  readonly resourceType: SharedResourceType;
  readonly resourceId: string;
  /** `user` (a person, by `email`), `organization` (a team workspace) or `public` (anyone with `url`). */
  readonly with: "user" | "organization" | "public";
  readonly access: ShareAccess;
  /** Who it's with, as the app names them. */
  readonly name: string | null;
  readonly email: string | null;
  readonly userId: string | null;
  readonly organizationId: string | null;
  /** A person without an account yet: they get it once they make one. */
  readonly pending: boolean;
  /** A public share's page. */
  readonly url: string | null;
  readonly createdAt: Date | null;
  readonly raw: JsonObject;
  readonly #client: NoClick | undefined;

  private constructor(raw: JsonObject, client?: NoClick) {
    this.id = String(raw.id);
    this.resourceType = raw.resource_type as SharedResourceType;
    this.resourceId = String(raw.resource_id);
    this.with = raw.with as Share["with"];
    this.access = raw.access as ShareAccess;
    this.name = (raw.name as string | null) ?? null;
    this.email = (raw.email as string | null) ?? null;
    this.userId = (raw.user_id as string | null) ?? null;
    this.organizationId = (raw.organization_id as string | null) ?? null;
    this.pending = raw.pending === true;
    this.url = (raw.url as string | null) ?? null;
    this.createdAt = parseTime(raw.created_at);
    this.raw = raw;
    this.#client = client;
  }

  /** Who `shared` (a `Workflow`, or an id with `resourceType`) is shared with. Only someone who manages its shares reads them. */
  static async list(shared: Shared, options: { resourceType?: SharedResourceType; client?: NoClick } = {}): Promise<Share[]> {
    const raw = asObject(await resolveClient(options.client).request("GET", "/v1/shares", {
      query: await resource(shared, options.resourceType), user: null,
    }));
    return (Array.isArray(raw.data) ? raw.data : []).map((row) => new Share(asObject(row), options.client));
  }

  /**
   * Share `resource` with a person by `email` (they're told; someone without an account gets it once they make one),
   * a team workspace (`organizationId`), or, for a workflow, anyone with the link (`public`, always to view). Sharing
   * again with the same one changes its `access`.
   */
  static async create(shared: Shared, options: {
    email?: string; organizationId?: string; public?: boolean; access?: ShareAccess;
    resourceType?: SharedResourceType; client?: NoClick;
  } = {}): Promise<Share> {
    const body: JsonObject = {
      ...(await resource(shared, options.resourceType)),
      access: options.access ?? "view",
      with: options.public ? "public" : options.organizationId ? "organization" : "user",
    };
    if (options.email !== undefined) body.email = options.email;
    if (options.organizationId !== undefined) body.organization_id = options.organizationId;
    return new Share(asObject(await resolveClient(options.client).request("POST", "/v1/shares", { json: body, user: null })), options.client);
  }

  /** Change what it allows. */
  async update(access: ShareAccess): Promise<Share> {
    return new Share(asObject(await resolveClient(this.#client).request("PATCH", `/v1/shares/${encodeURIComponent(this.id)}`, {
      json: { access }, user: null,
    })), this.#client);
  }

  /** End it: whoever it was with stops seeing the resource (sharing it again gives it back). */
  async delete(): Promise<void> {
    await resolveClient(this.#client).request("DELETE", `/v1/shares/${encodeURIComponent(this.id)}`, { user: null });
  }

  /**
   * Stop seeing something shared with you: your own share of it goes. False when there was none to drop (it reaches
   * you through a team workspace or a shared folder).
   */
  static async leave(shared: Shared, options: { resourceType?: SharedResourceType; client?: NoClick } = {}): Promise<boolean> {
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/shares/leave", {
      json: await resource(shared, options.resourceType), user: null,
    }));
    return raw.left === true;
  }

  /**
   * A personal workflow's invite link: whoever opens it signed in joins the workflow as a collaborator. Its owner
   * makes it the first time; anyone it's shared with reads the one that's on.
   */
  static async inviteLink(workflow: Shared, options: { client?: NoClick } = {}): Promise<ShareInviteLink> {
    const workflowId = String(await refId(workflow));
    const raw = asObject(await resolveClient(options.client).request("POST", "/v1/shares/invite_links", {
      json: { workflow_id: workflowId }, user: null,
    }));
    return { workflowId: String(raw.workflow_id), url: String(raw.url), token: String(raw.token), access: raw.access as ShareAccess };
  }
}
