/** Databases: SQLite by default, Postgres when you outgrow it. */

import { CONSOLE_BASE_URL, DEFAULT_BASE_URL } from "./client.ts";
import { TrashItem, trashed } from "./trash.ts";
import type { NoClick } from "./client.ts";
import { Conflict, NotFound } from "./errors.ts";
import { toExportBundle } from "./export.ts";
import type { ExportBundle } from "./export.ts";
import {
  ApiObject, asList, asObject, boundArguments, compact, createNamed, isoTime, listAll, listPage, num, paginate, parseTime, refId, str,
  toolEntries,
} from "./object.ts";
import type { AllowExisting, CallOptions, JsonObject, ObjectInit, Page, PageOptions, ReadOptions } from "./object.ts";
import type { PlacementOptions, RegionName } from "./region.ts";
import { Operation, registerResult } from "./operation.ts";
import { resolveScope } from "./scope.ts";

export type DatabaseEngine = "sqlite" | "postgres";
export type DatabaseStatus = "ready" | "restoring" | "branching";
/** `?` placeholders take an array, `:name` placeholders an object. */
export type SqlParams = readonly unknown[] | Readonly<Record<string, unknown>>;
/** One statement of a batch: the SQL alone, or the SQL and its parameters. */
export type SqlStatement = string | readonly [sql: string, params?: SqlParams];

/** An app that binds a database or a bucket, under its `binding` name. */
export interface UsedBy {
  kind: string;
  id: string;
  name: string;
  binding: string | null;
}

/**
 * What one statement returned: `rows` (an object per row, keyed by `columns`), and what it
 * touched (on SQLite the rows read and written, what it's billed on; on Postgres the rows
 * returned and changed, not billed). Iterating it yields the rows. `lastRowId` is the rowid an
 * insert made on SQLite (null on Postgres, where `returning` gives it).
 */
export class QueryResult implements Iterable<JsonObject> {
  readonly columns: string[];
  readonly rows: JsonObject[];
  readonly rowsRead: number;
  readonly rowsWritten: number;
  readonly lastRowId: number | null;
  readonly durationMs: number | null;
  readonly raw: JsonObject;

  /** @internal */
  constructor(result: unknown) {
    const raw = asObject(result);
    this.raw = raw;
    this.columns = Array.isArray(raw.columns) ? raw.columns.map(String) : [];
    this.rows = Array.isArray(raw.rows) ? raw.rows.map(asObject) : [];
    this.rowsRead = num(raw.rows_read) ?? 0;
    this.rowsWritten = num(raw.rows_written) ?? 0;
    this.lastRowId = num(raw.last_row_id);
    this.durationMs = num(raw.duration_ms);
  }

  get length(): number {
    return this.rows.length;
  }

  [Symbol.iterator](): Iterator<JsonObject> {
    return this.rows[Symbol.iterator]();
  }
}

/** A migration the database has applied, and the checksum of the SQL that ran. */
export interface Migration {
  name: string;
  appliedAt: Date | null;
  checksum: string | null;
  raw: JsonObject;
}

/** What `migrate` did: what it ran now, and what's still to run (everything new after a dry run). */
export interface MigrationResult {
  applied: string[];
  pending: string[];
  raw: JsonObject;
}

/** One column of a table. `default` is its default expression, or null. */
export interface Column {
  name: string;
  type: string;
  nullable: boolean;
  primaryKey: boolean;
  default: string | null;
}

/** A table: its columns in order and its row count (the planner's estimate on Postgres). */
export interface Table {
  name: string;
  columns: Column[];
  rowCount: number | null;
  raw: JsonObject;
}

/** Migrations to apply: `{ "0001_init.sql": "create table ..." }`, or `{ name, sql }` items. */
export type Migrations = Readonly<Record<string, string>> | readonly { name: string; sql: string }[];

export interface DatabaseCreateOptions extends CallOptions, PlacementOptions {
  /** `"sqlite"` (the default, cheap while idle) or `"postgres"`. */
  engine?: DatabaseEngine;
}

/** What a preview branch's copy of a SQLite database holds besides its schema: production's rows too. */
export type BranchData = "copy";

function wireParams(params: SqlParams | undefined): unknown {
  if (params === undefined) return undefined;
  const value = (v: unknown) => (v instanceof Date ? v.toISOString() : v);
  if (Array.isArray(params)) return params.map(value);
  return Object.fromEntries(Object.entries(params).map(([k, v]) => [k, value(v)]));
}

function statement(sql: string, params?: SqlParams): JsonObject {
  return compact({ sql, params: wireParams(params) });
}

function toMigration(value: unknown): Migration {
  const raw = asObject(value);
  return { name: str(raw.name) ?? "", appliedAt: parseTime(raw.applied_at), checksum: str(raw.checksum), raw };
}

function toTable(value: unknown): Table {
  const raw = asObject(value);
  const columns = (Array.isArray(raw.columns) ? raw.columns : []).map(asObject).map((c) => ({
    name: str(c.name) ?? "",
    type: str(c.type) ?? "",
    nullable: c.nullable !== false,
    primaryKey: c.primary_key === true,
    default: str(c.default),
  }));
  return { name: str(raw.name) ?? "", columns, rowCount: num(raw.row_count), raw };
}

/** @internal `{ name, sql }` in name order. */
function migrationList(migrations: Migrations): { name: string; sql: string }[] {
  const items = Array.isArray(migrations)
    ? [...(migrations as readonly { name: string; sql: string }[])]
    : Object.entries(migrations as Record<string, string>).map(([name, sql]) => ({ name, sql }));
  if (!items.length) throw new TypeError("migrate() got no migrations.");
  return items.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
}

const readDatabase = (result: unknown, op: Operation<unknown>): Database => Database._fromView(asObject(result), op._client, op._scope);

registerResult("database.restore", readDatabase);
registerResult("database.branch", readDatabase);
registerResult("database.export", toExportBundle);

/** What an agent, a toolkit or a hosted MCP server may do with a database, each a tool of its own. */
export const DATABASE_TOOLS = ["query", "execute", "schema"] as const;
/** `upsert` writes one row of the table bound to it; only `only(...)` gives it. */
export type DatabaseTool = (typeof DATABASE_TOOLS)[number] | "upsert";

/** Some of a database's operations as tools (`db.only(...)`), with the arguments `bind(...)` fixed. */
export class DatabaseOperations {
  readonly database: Database;
  readonly operations: DatabaseTool[];
  /** The arguments NoClick fills on every call, out of the model's reach. */
  readonly bindings: JsonObject;

  constructor(database: Database, operations: DatabaseTool[], bindings: JsonObject = {}) {
    this.database = database;
    this.operations = operations;
    this.bindings = bindings;
  }

  /**
   * Fix arguments of these operations, as `ConnectionOperations.bind` does. `upsert` needs `table`
   * bound; bind a column too and every row it writes carries that value.
   *
   *     leads.only("upsert").bind({ table: "enriched" })
   */
  bind(args: JsonObject): DatabaseOperations {
    return new DatabaseOperations(this.database, [...this.operations], { ...this.bindings, ...boundArguments(args) });
  }

  /** @internal */
  async _toolRefs(): Promise<(string | JsonObject)[]> {
    if (this.operations.includes("upsert") && !("table" in this.bindings)) {
      throw new TypeError('upsert writes to one table: bind it, db.only("upsert").bind({ table: "enriched" })');
    }
    return toolEntries(`database:${await refId(this.database)}`, this.operations, this.bindings);
  }
}

/**
 * A SQL database: SQLite (the default) or Postgres. `query` reads, `execute` and `batch` write,
 * `migrate` applies your schema. `Database.fromName("orders", { createIfMissing: true })` is lazy.
 * In an agent's or a toolkit's `tools` it is three tools, `{name}__query`, `{name}__execute` and
 * `{name}__schema`; `only(...)` picks some of them.
 */
export class Database extends ApiObject {
  private _createWith: JsonObject | null = null;
  private _branchData: BranchData | undefined;

  protected constructor(init: ObjectInit) {
    super(init);
  }

  /** @internal A database view from a listing or an operation's result. */
  static _fromView(raw: JsonObject, client: NoClick | undefined, user: ObjectInit["user"]): Database {
    return new Database({ raw, client, user });
  }

  /**
   * A tool ref to some of its operations, for `tools`: `"query"` (a read-only statement),
   * `"execute"` (a statement that writes) and `"schema"` (its tables and columns). The database
   * itself in `tools` gives all three. `"upsert"` writes one row of one table by its primary key,
   * its parameters that table's columns; bind its table with `.bind({ table })`.
   */
  only(...operations: DatabaseTool[]): DatabaseOperations {
    const unknown = operations.filter((op) => op !== "upsert" && !(DATABASE_TOOLS as readonly string[]).includes(op));
    if (!operations.length || unknown.length) {
      throw new TypeError(`only() takes some of ${DATABASE_TOOLS.join(", ")}, not ${unknown.join(", ") || "nothing"} (or upsert, with its table bound)`);
    }
    return new DatabaseOperations(this, operations);
  }

  /**
   * Create a database, unique by name per user (a taken name throws `Conflict` with `existingId`, or with
   * `allowExisting: true` returns the database already there, data and all).
   */
  static async create(name: string, options: DatabaseCreateOptions & AllowExisting = {}): Promise<Database> {
    const scope = resolveScope(options.user);
    const raw = await createNamed("/v1/databases", compact({ name, engine: options.engine ?? "sqlite", region: options.region }), {
      allowExisting: options.allowExisting, user: scope, client: options.client,
    });
    return new Database({ raw, client: options.client, user: scope });
  }

  /**
   * A lazy reference to the database called `name` for the current (or given) user. With
   * `createIfMissing` it's created on first use with `engine`; one that exists is used as it is.
   *
   * In a preview branch of an app whose `preview_resources` is `branch`, the branch gets its own copy
   * at its first write and reads production's as it is until then. A Postgres copy is a copy-on-write
   * branch of production's data; a SQLite copy holds the schema and migrations only (`migrate`'s `seed`
   * fills it), unless `branchData: "copy"` asks for production's rows too, read at one moment while
   * production keeps serving (up to 200,000 rows and 16 MB). It changes nothing outside a preview.
   */
  static fromName(name: string, options: DatabaseCreateOptions & { createIfMissing?: boolean; branchData?: BranchData } = {}): Database {
    const database = new Database({ hints: { name }, client: options.client, user: options.user });
    if (options.createIfMissing) database._createWith = compact({ name, engine: options.engine ?? "sqlite", region: options.region });
    database._branchData = options.branchData;
    return database;
  }

  static fromId(databaseId: string, options: CallOptions = {}): Database {
    return new Database({ hints: { id: databaseId }, client: options.client, user: options.user });
  }

  static async get(databaseId: string, options: CallOptions = {}): Promise<Database> {
    return await Database.fromId(databaseId, options).hydrate();
  }

  /** The current user's databases, branches included (or those `userFilter` covers). */
  static async list(options: ReadOptions & { engine?: DatabaseEngine; limit?: number } = {}): Promise<Database[]> {
    return await listAll(
      { ...options, path: "/v1/databases", query: { engine: options.engine } },
      (raw, user) => new Database({ raw, client: options.client, user }),
    );
  }

  /** One page of databases; pass `nextCursor` back as `cursor`. */
  static async listPage(options: ReadOptions & PageOptions & { engine?: DatabaseEngine } = {}): Promise<Page<Database>> {
    return await listPage(
      { ...options, path: "/v1/databases", query: { engine: options.engine } },
      (raw, user) => new Database({ raw, client: options.client, user }),
    );
  }

  get id(): string {
    return this._field("id");
  }
  get name(): string {
    return this._field("name");
  }
  get engine(): DatabaseEngine {
    return this._field("engine");
  }
  get status(): DatabaseStatus {
    return this._field("status");
  }
  get sizeBytes(): number | null {
    return this._field("size_bytes");
  }
  get tableCount(): number | null {
    return this._field("table_count");
  }
  /** The database a branch was made from (null if it isn't one). */
  get parentId(): string | null {
    return this._field("parent_id");
  }
  /** Who uses it: apps that bind it (`kind` `project`, with the binding name) and agents with it in their tools (`kind` `agent`). */
  get usedBy(): UsedBy[] {
    const rows = this._field<unknown>("used_by");
    return (Array.isArray(rows) ? rows : []).map(asObject).map((u) => ({
      kind: str(u.kind) ?? "project", id: str(u.id) ?? "", name: str(u.name) ?? "", binding: str(u.binding),
    }));
  }
  /** The region it keeps its data in, fixed when it was created. */
  get region(): RegionName | null {
    return this._field("region");
  }
  get userId(): string | null {
    return this._field("user_id");
  }
  /** The automation whose tables it holds (NoClick makes one for each automation that keeps tables), or null. */
  get workflow(): { id: string; name: string | null } | null {
    return this._field<{ id: string; name: string | null } | null>("workflow") ?? null;
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /** This database in the developer console (null off the hosted API). */
  get consoleUrl(): string | null {
    if (this._api.baseUrl !== DEFAULT_BASE_URL) return null;
    return `${CONSOLE_BASE_URL}/resources/databases?database=${encodeURIComponent(String(this._known("id")))}`;
  }

  protected async _load(): Promise<JsonObject> {
    const id = this._known("id");
    if (typeof id === "string") return await this._request<JsonObject>("GET", `/v1/databases/${id}`);
    const name = String(this._hints.name);
    const found = await this._inApp("database", name, this._createWith, { branch_data: this._branchData });
    if (found) return found;
    const page = await this._request("GET", "/v1/databases", { query: { name } });
    const row = (asList(page) as JsonObject[]).find((r) => r.name === name);
    if (row) return row;
    if (!this._createWith) {
      throw new NotFound(`No database is named "${name}".`, {
        nextStep: "Create it with Database.create(...) or pass { createIfMissing: true }.",
        details: { name, kind: "database" },
      });
    }
    try {
      return await this._request<JsonObject>("POST", "/v1/databases", { json: this._createWith });
    } catch (err) {
      if (!(err instanceof Conflict) || !err.existingId) throw err; // created concurrently: adopt it
      return await this._request<JsonObject>("GET", `/v1/databases/${err.existingId}`);
    }
  }

  /** This database's route; a reference by name is looked up (or created) first. */
  private async route(suffix = ""): Promise<string> {
    if (!this._known("id")) await this._ensure();
    return `/v1/databases/${String(this._known("id"))}${suffix}`;
  }

  private operation<T>(payload: unknown, kind: string, reader: (result: unknown, op: Operation<unknown>) => T): Operation<T> {
    return Operation._fromPayload<T>(payload, { client: this._client, user: this._callScope(), kind, reader });
  }

  /**
   * Run a read: one `select` (or `with ... select`). It runs read-only: a statement that writes
   * throws `InvalidRequest`; use `execute` for those. At most 10 MB of rows; 30 seconds. On
   * Postgres, `noclick.embed(:q, model)` turns a parameter or a quoted text into a `halfvec`
   * before the statement runs (up to 100 distinct texts a request; not over `connectionUrl`), so a
   * read (an agent's `query` tool too) can search by meaning (billed as AI to the database's user).
   *
   *     await kb.query("select id from articles order by embedding <=> noclick.embed(:q, :model) limit 5", { q, model });
   */
  async query(sql: string, params?: SqlParams): Promise<QueryResult> {
    return new QueryResult(await this._request("POST", await this.route("/query"), { json: { ...statement(sql, params), read_only: true } }));
  }

  /**
   * Run one statement that writes (several go in a `batch`). A SQLite database that would pass
   * 10 GB throws `QuotaExceeded`, whose next step is branching into Postgres.
   */
  async execute(sql: string, params?: SqlParams): Promise<QueryResult> {
    return new QueryResult(await this._request("POST", await this.route("/query"), { json: statement(sql, params) }));
  }

  /** Run up to 100 statements in one transaction: all apply or none do. */
  async batch(statements: readonly SqlStatement[]): Promise<QueryResult[]> {
    const wire = statements.map((s) => (typeof s === "string" ? statement(s) : statement(s[0], s[1])));
    const response = asObject(await this._request("POST", await this.route("/query"), { json: { statements: wire } }));
    return (Array.isArray(response.results) ? response.results : []).map((r) => new QueryResult(r));
  }

  /**
   * Apply the migrations the database hasn't run, in name order, in one transaction (a failing
   * one applies none). In Node, read your `migrations/*.sql` files into an object first.
   * `dryRun` reports what would run and changes nothing. `seed` is SQL run once, after them and in
   * their transaction, on a preview branch's database that holds none of production's data (a SQLite
   * copy made without its rows, or one only the branch has); production never runs it, and it shows
   * in `applied` as `(seed)`.
   */
  async migrate(migrations: Migrations, options: { dryRun?: boolean; seed?: string } = {}): Promise<MigrationResult> {
    const seed = options.dryRun ? undefined : options.seed;
    const json = compact({ migrations: migrationList(migrations), dry_run: options.dryRun ? true : undefined, seed });
    const raw = asObject(await this._request("POST", await this.route("/migrations"), { json }));
    const names = (value: unknown) => (Array.isArray(value) ? value.map(String) : []);
    return { applied: names(raw.applied), pending: names(raw.pending), raw };
  }

  /** The migrations this database has applied, oldest first. */
  async migrations(): Promise<Migration[]> {
    return (await paginate(this._api, await this.route("/migrations"), { user: this._callScope() ?? null })).map(toMigration);
  }

  /** The database's tables, their columns and row counts. */
  async schema(): Promise<Table[]> {
    return asList(await this._request("GET", await this.route("/schema"))).map(toTable);
  }

  /**
   * Put the database back as it was at `at` (within its history: 30 days on SQLite, 7 on
   * Postgres), in place. What it held just before is kept in the trash for 30 days as a database
   * copy (the operation's `keptCopyId`): `undo()` on the operation, or restoring that `TrashItem`,
   * puts it back. `wait()` resolves to this database, restored. To look at the past without
   * changing the present, `branch` at that time instead.
   */
  async restore(options: { at: Date | string }): Promise<Operation<Database>> {
    const payload = await this._request("POST", await this.route("/restore"), { json: { at: isoTime(options.at) } });
    return this.operation(payload, "database.restore", readDatabase);
  }

  /**
   * Copy the database into a new one called `name`, as it is now or as it was `at` (within its
   * history). `engine: "postgres"` branches SQLite into Postgres. While a SQLite database is
   * copied its `status` is `branching`. `wait()` resolves to the new `Database`.
   */
  async branch(name: string, options: { at?: Date | string; engine?: DatabaseEngine } = {}): Promise<Operation<Database>> {
    const json = compact({ name, at: isoTime(options.at), engine: options.engine });
    return this.operation(await this._request("POST", await this.route("/branches"), { json }), "database.branch", readDatabase);
  }

  /** The databases branched from this one. */
  async branches(): Promise<Database[]> {
    const rows = await paginate(this._api, await this.route("/branches"), { user: this._callScope() ?? null });
    return rows.map((raw) => new Database({ raw, client: this._client, user: this._callScope() }));
  }

  /**
   * A `postgresql://` URL with a password that stops working after `ttlS` seconds (default
   * 3600), when any session still open on it ends. SQLite throws `NotAvailable`. Treat it as a
   * secret.
   */
  async connectionUrl(options: { ttlS?: number; readOnly?: boolean } = {}): Promise<string> {
    const json = compact({ ttl_s: options.ttlS ?? 3600, read_only: options.readOnly ? true : undefined });
    return String(asObject(await this._request("POST", await this.route("/connection_url"), { json })).url);
  }

  /**
   * Export as SQL that recreates its schema and rows in any database of its engine:
   * `sqlite3 booking.db < databases/booking-db.sql`, or a `pg_dump` script for `psql` (NoClick's own
   * `noclick` schema, owners and grants left out). Exporting a Postgres database wakes it, and its
   * compute is billed as any use is. `wait()` resolves to an `ExportBundle`: a zip at `url` holding the dump.
   */
  async export(): Promise<Operation<ExportBundle>> {
    return this.operation(await this._request("POST", await this.route("/export")), "database.export", toExportBundle);
  }

  /**
   * Delete the database and its data: it goes to the trash, restorable for 30 days, and its
   * connection URLs stop working. One with branches or in an agent's tools throws `Conflict`. One an
   * app binds goes to the trash too: the app keeps its binding, reaching nothing until you restore
   * the database. Returns its `TrashItem`.
   */
  async delete(): Promise<TrashItem> {
    return trashed(await this._request("DELETE", await this.route()), this);
  }
}
