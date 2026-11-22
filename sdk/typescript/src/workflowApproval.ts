/**
 * A workflow's Approval steps: the runs that wait at one for a yes or a no, read and answered from your own code. A
 * run that reaches an Approval step waits there, for 7 days unless the step says otherwise. By default NoClick asks
 * your account's owner to answer it: a one-tap link on the app they text NoClick on (else by email), or a card in
 * the web chat while they're watching it. A step can name its own approver, the same shapes your account's approval
 * routing takes (`ApprovalPolicy.set({ routing })`, which an unset step follows): a person (`{ email }`), one of
 * your users (`{ user_id }`), one of your agents (`{ agent_id }`: it answers with its `approvals__answer` tool,
 * never on a run its own turn started) or your code (`{ code: true }`); how long they have (`expires_in_s`, 60
 * seconds to 7 days); and what happens when they don't answer (`on_timeout`: `"decline"` ends the run,
 * `"escalate"` asks the next approver up, finally the owner):
 *
 *     await invoices.addStep("approval", { settings: {
 *       title: "Pay this invoice?", approver: { agent_id: "Finance lead" }, on_timeout: "escalate",
 *       expires_in_s: 3600 } });
 *
 * Whoever it waits on, your code may answer it too, with one of your account's secret keys that names the
 * `approvals:answer` scope (a key with every scope, `*`, holds it only when it's named too).
 *
 *     const invoices = Workflow.fromName("Invoices");
 *     for (const approval of await invoices.approvals({ status: "pending" })) {
 *       if (Number(approval.values.amount ?? 0) < 500) await approval.approve({ note: "Under $500: fine." });
 *     }
 *
 * Whoever answers first decides: the run goes on once, down the step's approved or rejected branch, with the form's
 * values as they were answered, and every later answer throws `Conflict`, as one after its run ended unanswered
 * throws `Expired`.
 *
 * Rather than poll, your code can hear each one: a webhook subscribed to `workflow.approval.requested` gets it as its
 * run starts waiting, and to `workflow.approval.decided` as it's answered. The event's `data` is the approval as it
 * reads here, never its link:
 *
 *     const event = await Webhook.verify(body, headers, secret);
 *     if (event.type === "workflow.approval.requested") {
 *       await WorkflowApproval.fromId(String(event.data.workflow_id), String(event.data.id))
 *         .decline({ note: "Nothing is paid on weekends." });
 *     }
 */

import { resolveClient } from "./client.ts";
import { ApiObject, compact, listAll, parseTime } from "./object.ts";
import type { CallOptions, JsonObject, ReadOptions } from "./object.ts";

export type WorkflowApprovalStatus = "pending" | "approved" | "declined" | "expired";

/** One field of an Approval step's form. */
export interface WorkflowApprovalField {
  name: string;
  type: string;
  label: string;
  description: string;
  required: boolean;
  options: string[] | null;
}

export interface WorkflowApprovalListOptions extends ReadOptions {
  /** One status; omitted, every one. */
  status?: WorkflowApprovalStatus;
  /** The first this many (20 unless you say, at most 100). */
  limit?: number;
}

/** What an answer sends beside the decision. */
export interface WorkflowApprovalAnswer {
  /** Why, kept with the answer. */
  note?: string;
  /** The form's values as you answer it, by field name; left out, as the run asked. */
  values?: JsonObject;
}

/** A workflow, or its id. */
type WorkflowRef = string | { readonly id: string };

const idOf = (workflow: WorkflowRef): string => (typeof workflow === "string" ? workflow : workflow.id);

/** An Approval step a run of one of your workflows waits at (or waited at), as its owner sees it. */
export class WorkflowApproval extends ApiObject {
  /** A lazy reference to one of a workflow's Approval steps by its id (an event's `data.id`). */
  static fromId(workflow: WorkflowRef, approvalId: string, options: Pick<CallOptions, "client"> = {}): WorkflowApproval {
    return new WorkflowApproval({ hints: { id: approvalId, workflow_id: idOf(workflow) }, client: options.client, user: null });
  }

  /**
   * A workflow's Approval steps, newest first: the first 20, or the first `limit` (at most 100). Read as your
   * account, with a key holding `workflows` or `approvals:answer`.
   */
  static async list(workflow: WorkflowRef, options: WorkflowApprovalListOptions = {}): Promise<WorkflowApproval[]> {
    const path = `/v1/workflows/${encodeURIComponent(idOf(workflow))}/approvals`;
    return await listAll({ ...options, user: null, path, query: { status: options.status } },
      (raw) => new WorkflowApproval({ raw, client: options.client, user: null }));
  }

  get id(): string {
    return this._field("id");
  }
  get workflowId(): string {
    return this._field("workflow_id");
  }
  get workflowName(): string | null {
    return this._field("workflow_name");
  }
  /** The run that waits at it (`workflow.getRun(runId)`). */
  get runId(): string {
    return this._field("run_id");
  }
  /** The Approval step's id in the workflow. */
  get step(): string {
    return this._field("step");
  }
  /** What it asks, as the step's title says it. */
  get title(): string | null {
    return this._field("title");
  }
  /** Its form's fields. */
  get fields(): WorkflowApprovalField[] {
    return this._field("fields");
  }
  /** The form's values by field name: as the run asked, then as it was answered. */
  get values(): JsonObject {
    return this._field("values");
  }
  get status(): WorkflowApprovalStatus {
    return this._field("status");
  }
  get createdAt(): Date | null {
    return parseTime(this._field("created_at"));
  }
  /** When the approver it waits on must answer by (7 days after it was asked, unless the step's `expires_in_s` says
   *  otherwise; an escalation gives the next approver theirs). */
  get expiresAt(): Date | null {
    return parseTime(this._field("expires_at"));
  }
  /** Who it waits on (or waited on last): `kind` `owner`, `person` (with `email`), `user` (`user_id`), `agent`
   *  (`agent_id`) or `code`: the step's approver, else your account's, else the owner. */
  get approver(): JsonObject {
    return this._field("approver");
  }
  /** What happens if they don't answer by `expiresAt`: `decline` (the run ends) or `escalate` (the next approver up
   *  answers it, finally the owner). */
  get onTimeout(): "decline" | "escalate" | null {
    return this._field("on_timeout");
  }
  get decidedAt(): Date | null {
    return parseTime(this._field("decided_at"));
  }
  /**
   * Who decided: `owner` (signed in, or from NoClick's link or the web chat), `person` (a person or user named
   * approver, from the link NoClick emailed them), `agent` (an agent named approver), `code` or `app` (someone who
   * may edit the workflow, in the NoClick app); null while it waits.
   */
  get decidedBy(): "owner" | "person" | "agent" | "code" | "app" | null {
    return this._field("decided_by");
  }
  /** The key whose code decided (`key_id`, `key_name`); null otherwise. */
  get decidedByKey(): { key_id: string; key_name: string | null } | null {
    return this._field("decided_by_key");
  }
  /** The agent named approver that decided (`agent_id`, `name`); null otherwise. */
  get decidedByAgent(): { agent_id: string; name: string | null } | null {
    return this._field("decided_by_agent");
  }
  /** What whoever decided wrote with it. */
  get note(): string | null {
    return this._field("note");
  }
  /** Where NoClick sent the owner its link: `whatsapp`, `imessage`, `email`, or `web` (a card in the chat). */
  get sentTo(): string[] {
    return this._field("sent_to");
  }

  protected async _load(): Promise<JsonObject> {
    return await this._request<JsonObject>("GET", this.at(), { user: null });
  }

  private at(suffix = ""): string {
    const workflowId = encodeURIComponent(String(this._known("workflow_id")));
    return `/v1/workflows/${workflowId}/approvals/${encodeURIComponent(String(this._known("id")))}${suffix}`;
  }

  private async answer(approved: boolean, options: WorkflowApprovalAnswer): Promise<this> {
    this._raw = await resolveClient(this._client).request<JsonObject>("POST", this.at("/answer"), {
      json: compact({ approved, note: options.note, values: options.values }), user: null,
    });
    return this;
  }

  /**
   * Approve it from your own code, with one of your account's secret keys that names the `approvals:answer` scope:
   * the run goes on down the step's approved branch, once, with `values` (by field name) as the form's values where
   * you give them. Throws `PermissionDenied` for a key without the scope or one acting for a user, `Conflict` once
   * it was answered, and `Expired` once it lapsed unanswered.
   */
  approve(options: WorkflowApprovalAnswer = {}): Promise<this> {
    return this.answer(true, options);
  }

  /** Decline it from your own code, as `approve` answers it: the run goes on down the step's rejected branch. */
  decline(options: WorkflowApprovalAnswer = {}): Promise<this> {
    return this.answer(false, options);
  }
}
