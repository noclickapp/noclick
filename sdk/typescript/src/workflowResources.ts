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
 *
 * Making a file or a table, and adding, changing or taking out a table's rows, take edit access to its workflow, as
 * an interface's own uploads and writes do:
 *
 *     const menu = await WorkflowFile.create(intake, "menu.pdf", { sizeBytes: data.byteLength, mimeType: "application/pdf" });
 *     await fetch(menu.uploadUrl!, { method: "PUT", body: data, headers: { "Content-Type": "application/pdf" } });
 *     const signups = await WorkflowTable.create(intake, "Signups");
 *     await signups.addRows([{ email: "ada@example.com" }]);
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

/** What `WorkflowFile.create` takes beside the file's name. */
export interface NewWorkflowFileOptions {
  /** Its size in bytes, which the upload must match: at most 100 MB. */
  sizeBytes: number;
  /** Its type, which the upload sends as its `Content-Type` (`application/octet-stream` when left out). */
  mimeType?: string;
  /** The step that keeps it. */
  stepId?: string;
  /** What it holds (`image`, `video`, `audio`, `document`, `file`): read from `mimeType` when left out. */
  type?: string;
  client?: NoClick;
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

  /** One of your workflows' files by id, as `list` shows it, its `url` good for an hour. */
  static async get(fileId: string, options: { client?: NoClick } = {}): Promise<WorkflowFile> {
    const raw = await resolveClient(options.client).request("GET", `/v1/workflows/files/${encodeURIComponent(fileId)}`, { user: null });
    return new WorkflowFile({ raw: asObject(raw), client: options.client });
  }

  /**
   * Make a file of `workflow` to upload: put its bytes to `uploadUrl` in one PUT (`Content-Type` its `mimeType`,
   * exactly `sizeBytes` long). Once uploaded it reads for good at `permanentUrl`. Takes edit access to the workflow.
   *
   * @example
   * const menu = await WorkflowFile.create(Workflow.fromName("Cafe site"), "menu.pdf", { sizeBytes: data.byteLength, mimeType: "application/pdf" });
   * await fetch(menu.uploadUrl!, { method: "PUT", body: data, headers: { "Content-Type": "application/pdf" } });
   */
  static async create(workflow: Workflow | string, name: string, options: NewWorkflowFileOptions): Promise<WorkflowFile> {
    const workflowId = await refId(workflow);
    const raw = await resolveClient(options.client).request("POST", `/v1/workflows/${encodeURIComponent(String(workflowId))}/files`, {
      json: {
        name,
        size_bytes: options.sizeBytes,
        ...(options.mimeType ? { mime_type: options.mimeType } : {}),
        ...(options.stepId ? { step_id: options.stepId } : {}),
        ...(options.type ? { type: options.type } : {}),
      },
      user: null,
    });
    return new WorkflowFile({ raw: asObject(raw), client: options.client });
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
  /**
   * Only on a file `create` made: where its bytes go, in one PUT whose `Content-Type` is its `mimeType` and whose
   * length is its `sizeBytes`, until `uploadExpiresAt`.
   */
  get uploadUrl(): string | null {
    return (this.raw.upload_url as string | undefined) ?? null;
  }
  get uploadExpiresAt(): Date | null {
    return parseTime(this.raw.upload_expires_at);
  }
  /** Only on a file `create` made: where it reads for good once uploaded. Anyone holding it reads the file. */
  get permanentUrl(): string | null {
    return (this.raw.permanent_url as string | undefined) ?? null;
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  get updatedAt(): Date | null {
    return parseTime(this._field("updated_at"));
  }

  protected async _load(): Promise<JsonObject> {
    throw new Error("A workflow's file comes from WorkflowFile.list() or WorkflowFile.get().");
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

  /**
   * Make an empty table of `workflow`, as an interface or a Table step does. Takes edit access to the workflow.
   *
   * @example
   * const signups = await WorkflowTable.create(Workflow.fromName("Signups"), "Signups");
   * await signups.addRows([{ email: "ada@example.com" }]);
   */
  static async create(workflow: Workflow | string, name: string, options: { stepId?: string; client?: NoClick } = {}): Promise<WorkflowTable> {
    const workflowId = await refId(workflow);
    const raw = await resolveClient(options.client).request("POST", `/v1/workflows/${encodeURIComponent(String(workflowId))}/tables`, {
      json: { name, ...(options.stepId ? { step_id: options.stepId } : {}) },
      user: null,
    });
    return new WorkflowTable({ raw: asObject(raw), client: options.client });
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
   * Add `rows` at its end, in order, each an object of at most 1 MB as JSON; more than 10,000 go in as several calls.
   * Takes edit access to its workflow. Answers how many went in.
   */
  async addRows(rows: JsonObject[]): Promise<number> {
    let added = 0;
    for (let start = 0; start < rows.length; start += MAX_ROWS_PAGE) {
      const done = asObject(await this._request("POST", this.path("/rows"), { json: { rows: rows.slice(start, start + MAX_ROWS_PAGE) } }));
      added += typeof done.added === "number" ? done.added : 0;
    }
    return added;
  }

  /** Replace one row's data with `data`. Takes edit access to its workflow. */
  async updateRow(rowId: string, data: JsonObject): Promise<void> {
    await this._request("PATCH", this.path(`/rows/${encodeURIComponent(rowId)}`), { json: { data } });
  }

  /** Take rows out by id, for good; one it doesn't hold is passed by. Answers how many went. */
  async removeRows(rowIds: string[]): Promise<number> {
    let removed = 0;
    for (let start = 0; start < rowIds.length; start += MAX_ROWS_PAGE) {
      const done = asObject(await this._request("POST", this.path("/rows/remove"), { json: { row_ids: rowIds.slice(start, start + MAX_ROWS_PAGE) } }));
      removed += typeof done.removed === "number" ? done.removed : 0;
    }
    return removed;
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
