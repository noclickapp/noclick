/**
 * What your workflows keep: the files their steps and interfaces stored, and the tables they keep rows in.
 *
 *     const intake = Workflow.fromName("Order intake");
 *     for (const file of await WorkflowFile.list({ workflow: intake })) console.log(file.name, file.url);
 *     const [orders] = await WorkflowTable.list({ workflow: intake });
 *     console.log(orders.rowCount, (await orders.rows({ limit: 5 })).map((row) => row.data));
 *
 * A list holds what each workflow `Workflow.get` reads keeps: your account's own, those shared with it, and the
 * ones its agents run on. They're the account's, not any one user's: a call acting for one of your users (inside
 * `asUser`, or with a key held to one) is refused with `PermissionDenied`. An app's own code reads only what the
 * workflows its code made keep, one workflow at a time (`workflow`).
 * `organizationId` narrows a list to the workflows in a team workspace of the NoClick app your account belongs to
 * (`"none"`: those in no workspace). A file's `url` reads it for an hour after it's listed (a picture, PDF, sound or
 * video opens in place, anything else downloads); a table's rows read in pages of up to 10,000. Deleting either takes edit access to its workflow and is for good: nothing keeps a copy.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { ApiObject, asList, asObject, listAll, listPage, parseTime, refId } from "./object.ts";
import type { JsonObject, ObjectInit, Page, PageOptions } from "./object.ts";
import { Workflow } from "./workflow.ts";
import type { StepWorkspace } from "./workflow.ts";

/** The most rows one page of a table holds. */
const MAX_ROWS_PAGE = 10_000;

/** The workflow a list's item belongs to. */
export interface KeptBy {
  id: string;
  name: string;
  /**
   * What it's made of, at a glance: at most four of its step types, its triggers first, then its agents, then the
   * rest in the order it holds them (`["trigger-cron", "agent:codex", "automation-hubspot"]`). An agent on a coding
   * harness is `agent:<harness>`. Only step types and harness names, never a step's settings.
   */
  stepTypes: string[];
}

function keptBy(raw: unknown): KeptBy {
  const found = asObject(raw);
  return {
    id: String(found.id ?? ""),
    name: String(found.name ?? ""),
    stepTypes: Array.isArray(found.step_types) ? found.step_types.map(String) : [],
  };
}

/** Which of your workflows' files or tables a list holds. */
export interface WorkflowResourceListOptions {
  /** One workflow's (a `Workflow` or its id); an app's own code names one its code made. */
  workflow?: Workflow | string;
  /** The workflows in this team workspace of the NoClick app (its id; your account must belong to it), or `"none"`. */
  organizationId?: string;
  client?: NoClick;
}

async function filters(options: WorkflowResourceListOptions): Promise<Record<string, string | undefined>> {
  return { workflow_id: await refId(options.workflow), organization_id: options.organizationId };
}

/**
 * A file one of your workflows keeps: what a step or an interface uploaded or produced. `url` reads it until
 * `urlExpiresAt`; list again for a fresh one. Tables are apart (`WorkflowTable`).
 *
 * You read the files of each workflow `Workflow.get` reads: your account's own, those shared with it, and the ones
 * its agents run on. They're the account's: acting for one of your users, it's refused. An app's own code reads
 * only those of a workflow its code made, named with `workflow`.
 */
export class WorkflowFile extends ApiObject {
  protected constructor(init: ObjectInit) {
    super({ ...init, user: null });
  }

  /** Workflow routes are account-level. */
  override _callScope(): null {
    return null;
  }

  /** The files your workflows keep, most recently changed first: every workflow `Workflow.get` reads, or one. */
  static async list(options: WorkflowResourceListOptions & { limit?: number } = {}): Promise<WorkflowFile[]> {
    return await listAll({ ...options, path: "/v1/workflows/files", user: null, query: await filters(options) },
      (raw) => new WorkflowFile({ raw, client: options.client }));
  }

  /** One page of the files your workflows keep; pass `nextCursor` back as `cursor`. */
  static async listPage(options: WorkflowResourceListOptions & PageOptions = {}): Promise<Page<WorkflowFile>> {
    return await listPage({ ...options, path: "/v1/workflows/files", user: null, query: await filters(options) },
      (raw) => new WorkflowFile({ raw, client: options.client }));
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  /** The workflow that keeps it, and what it's made of. */
  get workflow(): KeptBy {
    return keptBy(this._field("workflow"));
  }
  /** Your account's access to that workflow: `owner`, `editor` or `viewer`. Deleting takes owner or editor. */
  get access(): string {
    return this._field("access");
  }
  /** The step that keeps it, when one does. */
  get stepId(): string | null {
    return this._field("step_id");
  }
  /** What it holds: `image`, `video`, `audio`, `document` or `file`. */
  get type(): string {
    return this._field("type");
  }
  get mimeType(): string | null {
    return this._field("mime_type");
  }
  get sizeBytes(): number {
    return this._field("size_bytes");
  }
  /**
   * A link that reads the file until `urlExpiresAt` (an hour after it's listed), naming nothing of where it's
   * stored: a picture, PDF, sound or video opens in place, anything else downloads. Null for a file with nothing
   * stored yet.
   */
  get url(): string | null {
    return this._field("url");
  }
  get urlExpiresAt(): Date | null {
    return parseTime(this._field("url_expires_at"));
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  get updatedAt(): Date | null {
    return parseTime(this._field("updated_at"));
  }

  protected async _load(): Promise<JsonObject> {
    throw new Error("A workflow's file comes from WorkflowFile.list().");
  }

  /**
   * Delete the file for good: its record and what it stored, with no trash to restore it from. A step that reads
   * it by its id finds nothing there. Takes edit access to its workflow, never one of your agents runs on
   * (`PermissionDenied` otherwise: change that through the agent).
   */
  async delete(): Promise<void> {
    await this._request("DELETE", `/v1/workflows/files/${encodeURIComponent(String(this._known("id")))}`);
  }
}

/** One row of a table: its position (`index`, from 0 in the order rows were added) and `data`, as it was written. */
export interface TableRow {
  id: string;
  index: number;
  data: JsonObject;
  createdAt: Date | null;
  raw: JsonObject;
}

/** One page of a table's rows, with how many rows the table holds. */
export interface RowsPage extends Page<TableRow> {
  totalCount: number;
}

function toTableRow(raw: JsonObject): TableRow {
  return {
    id: String(raw.id ?? ""),
    index: typeof raw.index === "number" ? raw.index : 0,
    data: asObject(raw.data),
    createdAt: parseTime(raw.created_at),
    raw,
  };
}

/**
 * A table one of your workflows keeps rows in (a Table step's, an interface's). Read its rows with `rows()`,
 * never by querying the database it names (`databaseId`): how a workflow lays its tables out there may change. You
 * read the tables of the workflows you read their files of (`WorkflowFile`).
 */
export class WorkflowTable extends ApiObject {
  protected constructor(init: ObjectInit) {
    super({ ...init, user: null });
  }

  /** Workflow routes are account-level. */
  override _callScope(): null {
    return null;
  }

  /** The tables your workflows keep, most recently changed first: every workflow `Workflow.get` reads, or one. */
  static async list(options: WorkflowResourceListOptions & { limit?: number } = {}): Promise<WorkflowTable[]> {
    return await listAll({ ...options, path: "/v1/workflows/tables", user: null, query: await filters(options) },
      (raw) => new WorkflowTable({ raw, client: options.client }));
  }

  /** One page of the tables your workflows keep; pass `nextCursor` back as `cursor`. */
  static async listPage(options: WorkflowResourceListOptions & PageOptions = {}): Promise<Page<WorkflowTable>> {
    return await listPage({ ...options, path: "/v1/workflows/tables", user: null, query: await filters(options) },
      (raw) => new WorkflowTable({ raw, client: options.client }));
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  /** The workflow that keeps it, and what it's made of. */
  get workflow(): KeptBy {
    return keptBy(this._field("workflow"));
  }
  /** Your account's access to that workflow: `owner`, `editor` or `viewer`. Deleting takes owner or editor. */
  get access(): string {
    return this._field("access");
  }
  /** The step that keeps it, when one does. */
  get stepId(): string | null {
    return this._field("step_id");
  }
  /** How many rows it holds. */
  get rowCount(): number | null {
    return this._field("row_count");
  }
  /** The database of your account's its rows are kept in (`Database.fromId`); null until they move there. */
  get databaseId(): string | null {
    return this._field("database_id");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  get updatedAt(): Date | null {
    return parseTime(this._field("updated_at"));
  }

  protected async _load(): Promise<JsonObject> {
    throw new Error("A workflow's table comes from WorkflowTable.list().");
  }

  private path(suffix = ""): string {
    return `/v1/workflows/tables/${encodeURIComponent(String(this._known("id")))}${suffix}`;
  }

  /**
   * One page of its rows in the order they were added (`limit`, 1 to 10,000; 100 when left out), with how many rows
   * the table holds (`totalCount`).
   */
  async rowsPage(options: PageOptions = {}): Promise<RowsPage> {
    const page = asObject(await resolveClient(this._client).request("GET", this.path("/rows"), {
      query: { cursor: options.cursor, limit: options.limit }, user: null,
    }));
    return {
      data: asList(page).map((raw) => toTableRow(asObject(raw))),
      nextCursor: page.next_cursor ? String(page.next_cursor) : null,
      totalCount: typeof page.total_count === "number" ? page.total_count : 0,
    };
  }

  /** Its rows in the order they were added: every one, read 10,000 at a time, or the first `limit`. */
  async rows(options: { limit?: number } = {}): Promise<TableRow[]> {
    const found: TableRow[] = [];
    let cursor: string | null = null;
    for (;;) {
      const limit: number = options.limit === undefined ? MAX_ROWS_PAGE : Math.min(options.limit - found.length, MAX_ROWS_PAGE);
      const page: RowsPage = await this.rowsPage({ cursor, limit });
      found.push(...page.data);
      if (page.nextCursor === null || (options.limit !== undefined && found.length >= options.limit)) {
        return options.limit === undefined ? found : found.slice(0, options.limit);
      }
      cursor = page.nextCursor;
    }
  }

  /**
   * Delete the table and every row in it for good, with no trash to restore it from. A step or an interface that
   * reads or adds to it fails on its next run. Takes edit access to its workflow, never one of your agents runs
   * on (`PermissionDenied` otherwise).
   */
  async delete(): Promise<void> {
    await this._request("DELETE", this.path());
  }
}

/**
 * One of your conversations with an agent step of a workflow, as a place its files are kept: what
 * `Step.workspace(conversation)` reads. You list those of your own conversations with the agent steps of every
 * workflow `Workflow.get` reads (never a share link's visitors', nor an agent's workflow: an agent keeps one
 * workspace, `agent.workspace()`). They're your people's, never one of your users': acting for one, it's refused.
 */
export class AgentStepWorkspace extends ApiObject {
  protected constructor(init: ObjectInit) {
    super({ ...init, user: null });
  }

  /** Workflow routes are account-level. */
  override _callScope(): null {
    return null;
  }

  /**
   * Your conversations' workspaces with agent steps, most recently active first, as Resources lists them;
   * `organizationId` narrows to a team workspace's workflows (`"none"`: those in no workspace).
   */
  static async list(options: { organizationId?: string; limit?: number; client?: NoClick } = {}): Promise<AgentStepWorkspace[]> {
    return await listAll(
      { ...options, path: "/v1/workflows/workspaces", user: null, query: { organization_id: options.organizationId } },
      (raw) => new AgentStepWorkspace({ raw, client: options.client }),
    );
  }

  /** The workflow the step is in, and what it's made of. */
  get workflow(): KeptBy {
    return keptBy(this._field("workflow"));
  }
  get stepId(): string {
    return this._field("step_id");
  }
  /** The agent step's name in the app. */
  get stepName(): string {
    return this._field("step_name");
  }
  /** The model the conversation last ran on. */
  get model(): string | null {
    return this._field("model");
  }
  /** The conversation, as `Step.workspace` takes it. */
  get conversation(): string {
    return this._field("conversation");
  }
  get title(): string {
    return this._field("title");
  }
  get lastActivity(): Date | null {
    return parseTime(this._field("last_activity"));
  }

  /** Its files, as `Step.workspace(conversation)` reads them. */
  async files(): Promise<StepWorkspace> {
    const workflow = Workflow.fromId(this.workflow.id, { client: this._client });
    return await workflow.step(this.stepId).workspace(this.conversation);
  }

  protected async _load(): Promise<JsonObject> {
    throw new Error("An agent step's workspace comes from AgentStepWorkspace.list().");
  }
}
