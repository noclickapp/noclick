/**
 * NoClick's example workflows: the ones its builder studies before it builds, each what it's for, guidance text, a
 * workflow, or both. The same for every account.
 *
 *     for (const example of await workflowExamples("triage support email", { limit: 3 })) {
 *       console.log(example.name, example.stepTypes);
 *     }
 *     const example = await workflowExample(id);
 *     console.log(example.text, (example.graph?.nodes as JsonObject[]).map((node) => node.type));
 */

import { resolveClient } from "./client.ts";
import type { NoClick } from "./client.ts";
import { asList, asObject, paginate, parseTime, str } from "./object.ts";
import type { JsonObject } from "./object.ts";

/** One of NoClick's example workflows: one of `workflowExamples()`. */
export interface WorkflowExample {
  id: string;
  name: string;
  /** What it's for, and when it applies. */
  description: string | null;
  /** Whether it holds guidance text. */
  hasText: boolean;
  /** Whether it holds a workflow. */
  hasWorkflow: boolean;
  /** What its workflow is made of, at a glance, as `Workflow.stepTypes` says it: its triggers first, then its agents, then the rest. */
  stepTypes: string[];
  updatedAt: Date | null;
  /** Its guidance, in Markdown; null in a listing (`workflowExample()` reads it). */
  text: string | null;
  /**
   * Its workflow as `workflow.graph()` reads a workflow's (`nodes`, each with its `type` and `config`, and `edges`),
   * without the connections or test outputs of the account it was made in, never a secret; null in a listing and for
   * one that's guidance only.
   */
  graph: JsonObject | null;
  raw: JsonObject;
}

function toExample(raw: JsonObject): WorkflowExample {
  return {
    id: String(raw.id),
    name: String(raw.name),
    description: str(raw.description),
    hasText: raw.has_text === true,
    hasWorkflow: raw.has_workflow === true,
    stepTypes: asList(raw.step_types).map(String),
    updatedAt: parseTime(raw.updated_at),
    text: str(raw.text),
    graph: raw.graph ? asObject(raw.graph) : null,
    raw,
  };
}

/**
 * NoClick's own example workflows, the ones its builder studies before it builds, most recently changed first; with
 * `query`, the ones it finds by name, what they're for and their text, the best first. A listing leaves each one's
 * text and workflow out: `workflowExample()` reads them. Fetched page by page, or the first `limit`. Needs the
 * `workflows` scope.
 *
 *     const [best] = await workflowExamples("post new form answers to Slack", { limit: 1 });
 *     const example = await workflowExample(best.id);
 *     console.log(example.text);
 */
export async function workflowExamples(
  query?: string,
  options: { limit?: number; client?: NoClick } = {},
): Promise<WorkflowExample[]> {
  const rows = await paginate(resolveClient(options.client), "/v1/workflow_examples", {
    query: { q: query }, user: null, limit: options.limit,
  });
  return rows.map(toExample);
}

/**
 * One of NoClick's example workflows whole: its guidance `text` and its workflow's `graph` (each null where it has
 * none). An id that names none throws `NotFound`. Needs the `workflows` scope.
 *
 *     const example = await workflowExample("6f1c2e9a-3b7d-4f0e-9a51-2d8c4b7e1a03");
 *     console.log(example.description, example.stepTypes);
 */
export async function workflowExample(exampleId: string, options: { client?: NoClick } = {}): Promise<WorkflowExample> {
  const raw = await resolveClient(options.client).request("GET", `/v1/workflow_examples/${encodeURIComponent(exampleId)}`, {
    user: null,
  });
  return toExample(asObject(raw));
}
