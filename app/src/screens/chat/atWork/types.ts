// The shapes the tab of what's at work reads, field for field from the /v1 views that answer them, as far as it reads
// them. What the tab shows is derived from these in model.ts.
import type { ApprovalView } from '../approvals';

// ── GET /v1/agents/coding ─────────────────────────────────────────────────────

export type CodingHarness = 'claude_code' | 'codex' | 'opencode' | 'hermes' | 'openclaw';
export type CodingState = 'working' | 'waiting' | 'warm' | 'paused' | 'stopped';
export type CodingPlace = 'live' | 'sandbox' | 'machine';
export type PauseReason = 'expired' | 'disconnected' | 'spending_paused' | 'spend_cap' | 'out_of_funds' | 'budget' | 'failed_start' | 'paused';

export interface Pause {
    reason: PauseReason;
    message: string;
}

/** Whose model credential it thinks with: NoClick's own key carries no connection. */
export type CodingCredential =
    | { kind: 'noclick'; connection: null; credential_type: null }
    | { kind: 'key' | 'plan' | 'pending'; connection: string; credential_type: string | null; connected: boolean };

/** Its turn in flight (or a lost one): `title` as whoever handed it over named it, `text` the first 200 characters of
 *  what it was asked. */
export interface CodingJob {
    operation_id: string;
    conversation: string | null;
    status: 'queued' | 'running' | 'awaiting_human';
    step: string | null;
    since: string;
    title: string | null;
    text: string;
    /** The workstream it belongs to, as it reads now; null where whoever handed it over named none. */
    workstream?: { id: string; name: string } | null;
    lost?: true;
    place_seen?: false;
}

/** A conversation with a place up now. */
export interface CodingRun {
    conversation: string | null;
    place: CodingPlace;
    since: string | null;
    project_id?: string;
    daemon?: boolean;
    busy: boolean;
}

export interface ModelUsage {
    input_tokens: number;
    output_tokens: number;
    cached_tokens: number;
    usd: number;
}

export interface CodingAgent {
    object: 'coding_agent';
    agent_id: string;
    name: string;
    user_id: string | null;
    /** Its app: `name` the identifier code finds it by, `title` as a person reads it. */
    app: { project_id: string; name: string | null; title: string | null; coder: boolean } | null;
    harness: CodingHarness;
    model: string;
    credential: CodingCredential;
    place: CodingPlace;
    state: CodingState;
    paused: Pause | null;
    pauses: Pause[];
    job: CodingJob | null;
    runs: CodingRun[];
    spent_usd_this_month: number;
    model_usage_this_month: ModelUsage;
}

export interface CodingAgentsPage {
    object: 'list';
    data: CodingAgent[];
    read_at: string;
    unread?: string[];
}

// ── An app, as GET /v1/projects lists it ──────────────────────────────────────

export interface ProjectSlice {
    object: 'project';
    id: string;
    name: string;
    title: string;
    /** Its first domain's address, else its own host. */
    url: string;
    repo_id: string | null;
    /** The deployment production serves; null before anything is deployed. */
    production: { id: string; url: string | null; status: string } | null;
}

// ── An app's live session (GET /v1/projects/{id}/live; live/protocol.py SessionView) and its edits ──

export interface LiveSessionSlice {
    object: 'live_session';
    id: string;
    project_id: string;
    state: 'warming' | 'live' | 'idle' | 'ending' | 'ended' | 'failed';
    git: { branch: string; head: string | null; pushed: string | null; dirty: boolean } | null;
    edits: { count: number; last_seq: number };
}

export interface LiveState {
    object: 'live';
    project_id: string;
    session: LiveSessionSlice | null;
}

/** One edit as Vite took it (GET /v1/projects/{id}/live/edits, protocol.py EditFeedback). */
export interface EditFeedback {
    seq: number;
    files: string[];
    outcome: 'hot' | 'reload' | 'error' | 'none';
}

export interface EditsPage {
    object: 'list';
    data: EditFeedback[];
    last_seq: number;
    session: { id: string; state: string } | null;
}

/** An app's session and its newest edits, newest last. */
export interface LiveRead {
    session: LiveSessionSlice | null;
    edits: EditFeedback[];
}

// ── An operation the chat follows, as its card's job reads it (@/sdk/useFollowedOperations `jobOf`) ──

/** What a child told its parent last (`jobs.update_view`). */
export interface JobUpdate {
    kind: 'done' | 'blocked' | 'before' | 'every' | 'message';
    text: string | null;
    waiting_on: { kind: string; url?: string | null } | null;
    created_at: string;
}

export interface FollowedOperation {
    id: string;
    kind: string;
    /** As the chat's jobs name it: queued and running are running, awaiting_human is waiting. */
    status: 'running' | 'waiting' | 'completed' | 'failed' | 'cancelled';
    step: string | null;
    /** The work in a few words, as whoever started it named it; null on work started before titles. */
    title: string | null;
    /** Its whole text's first 120 characters (a task's, a run's automation). */
    summary: string | null;
    /** The workstream its work belongs to, as it reads now; null where nobody named one. */
    workstream: { id: string; name: string } | null;
    agent_id: string | null;
    latest_update: JobUpdate | null;
    created_at: string;
    finished_at: string | null;
}

// ── An agent (agents/service.py `agent_view`), the fields the tab reads ─────

export interface AgentSlice {
    object: 'agent';
    id: string;
    name: string;
    model: string;
    harness: 'sdk' | CodingHarness;
    /** What it checks out. */
    repos: { repo_id: string; branch: string; push: string[] }[];
}

// ── A held purchase or deletion waiting on the owner (gate/approvals.py `view`) ──

/** GET /v1/approvals lists the same view GET /v1/approvals/{id} answers, so a listed one is reviewed as it stands. */
export type HeldApproval = ApprovalView;

/** One call of a turn as its conversation's history shows it (agents/service.py `tool_call_entry`); a coding
 *  harness's own steps add `source: "harness"`. */
export interface ToolCallEntry {
    tool: string;
    arguments: Record<string, unknown>;
    result: string | null;
    is_error: boolean;
    created_at: string | null;
    source?: 'harness';
}
