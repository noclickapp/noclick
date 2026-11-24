/**
 * Step types: every kind of step a workflow can hold, NoClick's own (triggers, agents, conditions, loops,
 * interfaces, tables, code) and every integration's, with the settings each takes.
 *
 *     for (const kind of await stepTypes("send an email", { limit: 3 })) {
 *       console.log(kind.type, kind.label, kind.operations.slice(0, 3).map((op) => op.name));
 *     }
 *     const gmail = await stepType("automation-gmail");
 *     console.log(gmail.schema?.properties);
 *
 * A step's `type` is what `workflow.addStep` takes; `operations` what its `operation` takes; its `schema` the
 * settings `settings` takes, as the app's canvas draws a step's form from it. `Connection.integrations()` is the
 * catalog of services an account connects; this one holds every step.
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asList, asObject, paginate, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** What a step of a type can be in a workflow: a run starts from it, or an agent uses it as its tools. */
export type StepTypeKind = "trigger" | "tool";

/** One operation a step of the type runs: what `operation` takes. */
export interface StepTypeOperation {
  name: string;
  label: string | null;
  /** What it does; null in a listing (`stepType()` reads it). */
  description: string | null;
  /** Whether it starts runs (a trigger operation, `x-is-trigger`) rather than acting when a run reaches it. */
  trigger: boolean;
  /**
   * Whether running it needs an account connected to the step: false when it runs on NoClick's key with no account
   * (web search, public data) or the type takes none; true otherwise, also when the need depends on its settings.
   */
  needsAccount: boolean;
  raw: JsonObject;
}

/** The accounts a step of the type connects to (`step.setConnection`). */
export interface StepTypeConnection {
  /** Whether every operation needs one, so a step of it can't run without. */
  needed: boolean;
  /**
   * Its name in `Connection.integrations()` (`integration` when you make a connection for it), or null for a step
   * whose account isn't connected there (an agent's model key).
   */
  integration: string | null;
  /** The credential types its settings take, as a step's `connections` names them. */
  credentialTypes: string[];
  raw: JsonObject;
}

/** A kind of step a workflow can hold: one of `stepTypes()`. */
export interface StepType {
  /** What `workflow.addStep` takes, as a workflow's graph names it: `automation-slack`, `agent`, `trigger-cron`. */
  type: string;
  /** Its name in the app (`Slack`, `AI Agent`, `Schedule`). */
  label: string | null;
  description: string | null;
  /** The section the app lists an integration under (`communication`, `crm-sales`); null for NoClick's own. */
  category: string | null;
  /** What a step of it can be in a workflow: `trigger` (a run starts from it) and `tool` (an agent's tools). */
  kinds: StepTypeKind[];
  /** Whether a step of it starts runs whatever its operation (a trigger step: a schedule, a webhook, a form). */
  trigger: boolean;
  /**
   * Each operation once, its triggers first, in the order the app lists them; empty for a type that has none
   * (`trigger-run`). A read narrowed by `kind`, `query` or `operation` holds only those it kept.
   */
  operations: StepTypeOperation[];
  /** How many operations the type has in all, whatever a read kept; null in a listing. */
  operationsTotal: number | null;
  /** The accounts it connects to; null for a type whose settings take none. */
  connection: StepTypeConnection | null;
  /**
   * Why its service is gone and since when (`reason`, `since`), or null while it works. A listing leaves retired
   * types out; `stepType()` still reads one, since a step saved on it still loads and runs.
   */
  retired: JsonObject | null;
  /**
   * The JSON Schema of a step's settings, as the app's canvas draws its form from it (`properties.config`, a member
   * per operation where it has several, with the canvas's `x-` and `ui:` extensions). Null in a listing, and for a
   * type that takes no settings.
   */
  schema: JsonObject | null;
  raw: JsonObject;
}

function toOperation(raw: JsonObject): StepTypeOperation {
  return {
    name: String(raw.name),
    label: str(raw.label),
    description: str(raw.description),
    trigger: raw.trigger === true,
    needsAccount: raw.needs_account === true,
    raw,
  };
}

function toConnection(raw: unknown): StepTypeConnection | null {
  if (!raw || typeof raw !== "object") return null;
  const row = asObject(raw);
  return {
    needed: row.needed === true,
    integration: str(row.integration),
    credentialTypes: asList(row.credential_types).map(String),
    raw: row,
  };
}

function toStepType(raw: JsonObject): StepType {
  return {
    type: String(raw.type),
    label: str(raw.label),
    description: str(raw.description),
    category: str(raw.category),
    kinds: asList(raw.kinds) as StepTypeKind[],
    trigger: raw.trigger === true,
    operations: asList(raw.operations).map((op) => toOperation(asObject(op))),
    operationsTotal: typeof raw.operations_total === "number" ? raw.operations_total : null,
    connection: toConnection(raw.connection),
    retired: raw.retired ? asObject(raw.retired) : null,
    schema: raw.schema ? asObject(raw.schema) : null,
    raw,
  };
}

/**
 * Every kind of step a workflow can hold, NoClick's own first, then the integrations most used first; with
 * `query`, those it finds by name or by what they do, the best first, as the app's builder searches. `kind: "trigger"`
 * keeps the types a run starts from (a trigger step, or one with a trigger operation), `kind: "tool"` those an agent
 * uses as its tools. A listing leaves out each operation's description and the settings schema: `stepType()` reads
 * them. Fetched page by page, or the first `limit`. Needs the `workflows` scope.
 *
 *     const [send] = await stepTypes("send an email", { limit: 1 });
 *     await Workflow.fromName("Morning brief").addStep(send.type, { operation: send.operations[0].name });
 *
 *     for (const kind of await stepTypes(undefined, { kind: "trigger" })) {
 *       console.log(kind.type, kind.operations.filter((op) => op.trigger).map((op) => op.name));
 *     }
 */
export async function stepTypes(
  query?: string,
  options: { kind?: StepTypeKind; limit?: number; client?: NoClick } = {},
): Promise<StepType[]> {
  const rows = await paginate(resolveClient(options.client), "/v1/step_types", {
    query: { q: query, kind: options.kind }, user: null, limit: options.limit,
  });
  return rows.map(toStepType);
}

/** What one of a type's operations is: one that starts a workflow, or one a run does. */
export type StepTypeOperationKind = "trigger" | "action";

/**
 * One step type, each operation with its `description` (its triggers first), and its `schema`: what a step's
 * `settings` take, as the app's canvas draws its form from it (null for a type that takes no settings). `name` is the
 * type as a workflow's graph names it (`automation-gmail`, `agent`); an unknown one throws `NotFound` naming the
 * nearest. A type can be large (Stripe holds 491 operations): `kind`, `query` (the operations its words fit, the best
 * first) and `operation` (one name, or several) keep only some, and the `schema` only their settings;
 * `operationsTotal` still counts them all. An operation the type doesn't have throws `InvalidRequest`. Needs the
 * `workflows` scope.
 *
 *     const gmail = await stepType("automation-gmail");
 *     const send = gmail.operations.find((op) => op.name === "send_email_message");
 *     console.log(send?.description, gmail.connection?.credentialTypes);
 *
 *     const stripe = await stepType("automation-stripe", { kind: "trigger", query: "payment failed" });
 *     const failed = await stepType("automation-stripe", { operation: stripe.operations[0].name });
 */
export async function stepType(
  name: string,
  options: { kind?: StepTypeOperationKind; query?: string; operation?: string | string[]; client?: NoClick } = {},
): Promise<StepType> {
  const operation = Array.isArray(options.operation) ? options.operation.join(",") : options.operation;
  const raw = await resolveClient(options.client).request("GET", `/v1/step_types/${encodeURIComponent(name)}`, {
    query: { kind: options.kind, q: options.query, operation: operation || undefined }, user: null,
  });
  return toStepType(asObject(raw));
}

/** Whether settings of a step type would run (`checkStepSettings`): `valid`, the `errors` in the way, and the set
 *  of settings they meet (`satisfiedSet`, `default`; null when none). */
export interface StepSettingsCheck {
  stepType: string;
  valid: boolean;
  errors: unknown[];
  satisfiedSet: string | null;
  raw: JsonObject;
}

/**
 * Whether `settings` of the step type `name` would run, as a run judges them (a form's, saved or not): nothing is read
 * or written. Needs the `workflows` scope.
 *
 *     const check = await checkStepSettings("log", { message: "Hello" });
 *     if (!check.valid) console.log(check.errors);
 */
export async function checkStepSettings(
  name: string,
  settings: JsonObject,
  options: { client?: NoClick } = {},
): Promise<StepSettingsCheck> {
  const raw = asObject(await resolveClient(options.client).request(
    "POST", `/v1/step_types/${encodeURIComponent(name)}/check`, { json: { settings }, user: null }));
  return {
    stepType: String(raw.step_type ?? name), valid: raw.valid === true,
    errors: Array.isArray(raw.errors) ? raw.errors : [],
    satisfiedSet: typeof raw.satisfied_set === "string" ? raw.satisfied_set : null, raw,
  };
}

/**
 * What a step of a type outputs, as your account's own runs and events of it showed it (and those of people in a
 * workspace with you), never another account's: `shape`, its fields' names and types, with `suggestedRefs`, the few
 * references worth offering first (null until they're made). `shape` is null until your first run or event of it.
 */
export interface StepOutputShape {
  type: string;
  operation: string;
  shape: JsonObject | null;
  suggestedRefs: unknown[] | null;
  raw: JsonObject;
}

/**
 * What a step of type `name` outputs (its `operation`'s, for a type with several), learned from your account's own runs:
 * the fields a later step's settings can reference, as the app's canvas offers them. Needs the `workflows` scope.
 *
 *     const { shape } = await stepOutputShape("automation-hubspot", { operation: "get_contact" });
 *     console.log(Object.keys(shape?.properties ?? {}));
 */
export async function stepOutputShape(
  name: string,
  options: { operation?: string; client?: NoClick } = {},
): Promise<StepOutputShape> {
  const raw = asObject(await resolveClient(options.client).request(
    "GET", `/v1/step_types/${encodeURIComponent(name)}/output_shape`, { query: { operation: options.operation }, user: null },
  ));
  return {
    type: String(raw.type),
    operation: String(raw.operation),
    shape: raw.shape ? asObject(raw.shape) : null,
    suggestedRefs: Array.isArray(raw.suggested_refs) ? raw.suggested_refs : null,
    raw,
  };
}

/** One of a step type's choices (`stepTypeOptions`): what the setting takes, its label and the service's metadata. */
export interface StepTypeOption {
  value: unknown;
  label: unknown;
  metadata: JsonObject | null;
}

/** A page of a step type's choices for one field (`stepTypeOptions`); pass `nextPageToken` back as `pageToken`. */
export interface StepTypeOptions {
  type: string;
  field: string;
  options: StepTypeOption[];
  nextPageToken: string | null;
  /** By path, a choice or a part of one left out because it held a secret. */
  withheld: string[];
  raw: JsonObject;
}

/**
 * The choices a step of type `name` lists for `field` (the name its loader takes, a setting's
 * `x-dynamic-options.field_name`), for no step of a workflow: a picker outside a step's form. Read through
 * `connection`, an account you may use (its ref or credential id), with `settings` what the list depends on;
 * `workflowId` names the workflow the choices are for, which a loader may read. A step's own dropdown is
 * `Step.options`. Needs the `workflows` scope.
 *
 *     const page = await stepTypeOptions("automation-slack", "channel", { connection: "credential:7c1…" });
 *     console.log(page.options.map((o) => o.label));
 */
export async function stepTypeOptions(
  name: string,
  field: string,
  options: {
    connection?: string; settings?: JsonObject; workflowId?: string; search?: string; pageToken?: string;
    client?: NoClick;
  } = {},
): Promise<StepTypeOptions> {
  const json: JsonObject = { field };
  if (options.connection !== undefined) json.connection = options.connection;
  if (options.settings !== undefined) json.settings = options.settings;
  if (options.workflowId !== undefined) json.workflow_id = options.workflowId;
  if (options.search !== undefined) json.search = options.search;
  if (options.pageToken !== undefined) json.page_token = options.pageToken;
  const raw = asObject(await resolveClient(options.client).request(
    "POST", `/v1/step_types/${encodeURIComponent(name)}/options`, { json, user: null },
  ));
  return {
    type: String(raw.type),
    field: String(raw.field),
    options: asList(raw.options).map((option) => {
      const found = asObject(option);
      return { value: found.value ?? null, label: found.label ?? null, metadata: found.metadata ? asObject(found.metadata) : null };
    }),
    nextPageToken: str(raw.next_page_token),
    withheld: asList(raw.withheld).map(String),
    raw,
  };
}
